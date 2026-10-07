# TenantFlow

Uma API de projetos e tarefas para empresas que dividem a mesma infraestrutura, mas precisam manter seus dados separados.

Imagine duas equipes: a Aurora está preparando seu novo site; a Horizonte está organizando uma campanha. As duas usam a mesma API. Cada uma vê apenas seus projetos, tarefas e colegas, mesmo que alguém tente abrir diretamente o identificador de um recurso da outra empresa.

O projeto foi pensado para portfólio: tem um domínio simples, decisões explicadas e testes que procuram quebrar as garantias de isolamento e de uso dos planos.

## Veja a API funcionando

Uma demonstração de **2min53s**, com narração em português e legendas. O vídeo explica o cadastro, a criação de projetos e tarefas, o isolamento entre duas empresas e a mudança de plano, usando resultados de chamadas reais à API.

[![Assista à demonstração do TenantFlow](docs/videos/tenantflow-capa.png)](https://github.com/YannSantana/tenantflow/raw/refs/heads/main/docs/videos/tenantflow-como-funciona.mp4)

[Assistir ou baixar o vídeo (MP4)](https://github.com/YannSantana/tenantflow/raw/refs/heads/main/docs/videos/tenantflow-como-funciona.mp4) · [Legendas (SRT)](docs/videos/tenantflow-legendas.srt)

## O que já funciona

- Cadastro de empresa com seu primeiro administrador e login com token temporário.
- Equipe com administradores e membros; apenas administradores gerenciam usuários e assinatura.
- Criação, consulta, edição e exclusão de projetos e tarefas, com listas paginadas.
- Planos Free, Pro e Business, com limites de usuários, projetos e requisições mensais.
- Assinaturas ativas, canceladas e expiradas. A alteração de plano é uma simulação; nenhum pagamento é processado.
- Isolamento no SQLAlchemy e no PostgreSQL, com conta de banco restrita.
- Logs JSON, identificador de requisição e métricas protegidas por uma credencial própria.
- Prometheus e um painel do Grafana provisionados pelo Docker Compose.
- Testes automatizados, incluindo concorrência no PostgreSQL real, e execução no GitHub Actions.

## Como executar

Você precisa de Docker com Compose. Para gerar a configuração e rodar a demonstração, use também Python 3.12 ou superior.

Abra o terminal nesta pasta e execute:

```sh
python scripts/setup_env.py
docker compose up --build -d
```

O primeiro comando gera segredos próprios em `.env` sem sobrescrever uma configuração existente. O segundo inicia o banco, a API e o monitoramento. Na primeira inicialização do volume, o PostgreSQL aplica `database/001_initial.sql`.

| Onde acessar | Endereço |
| --- | --- |
| Documentação interativa da API | http://localhost:8000/docs |
| Disponibilidade da API e do banco | http://localhost:8000/health |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

Entre no Grafana com `admin` e `local-grafana-only`. Abra a pasta **TenantFlow**, onde o painel já estará disponível. As senhas do banco e do Grafana no Compose são credenciais locais de demonstração. Os serviços publicados escutam apenas em `127.0.0.1`.

Para acompanhar os logs ou parar os serviços:

```sh
docker compose logs -f api
docker compose down
```

Os dados permanecem nos volumes após parar o ambiente. A migração inicial não é reaplicada a um volume já existente.

## Uma demonstração em dois minutos

Com a API funcionando:

```sh
python -m venv .venv
# Windows PowerShell:
.venv/Scripts/Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/demo.py
```

O roteiro cria Aurora e Horizonte, registra um projeto e uma tarefa na Aurora e tenta consultar esse projeto usando a conta da Horizonte. O resultado esperado é **404**. Depois, muda a Aurora para o plano Pro. Cada execução usa identificadores novos e deixa os dados no banco para exploração.

Você também pode começar pelo `POST /auth/register` na documentação interativa:

```json
{
  "company_name": "Aurora",
  "company_slug": "aurora",
  "email": "admin@aurora.example",
  "password": "UmaSenhaBoa123!"
}
```

Copie o `access_token` retornado e clique em **Authorize**. Informe apenas o token. A partir desse momento, os pedidos autenticados usam a empresa daquela conta. Para entrar novamente, use `POST /auth/login` com `company_slug`, `email` e `password`.

## Endpoints principais

| Ação | Endpoint | Quem pode usar |
| --- | --- | --- |
| Criar empresa / entrar | `POST /auth/register`, `POST /auth/login` | Público |
| Ver conta e empresa | `GET /me` | Autenticado |
| Consultar planos | `GET /plans` | Público |
| Consultar assinatura e uso | `GET /subscription` | Autenticado |
| Mudar plano ou estado | `PATCH /subscription` | Administrador |
| Listar / adicionar colegas | `GET /users`, `POST /users` | Autenticado / administrador |
| Remover colega | `DELETE /users/{id}` | Administrador |
| Listar / criar projetos | `GET /projects`, `POST /projects` | Assinatura ativa |
| Consultar / editar / excluir projeto | `GET`, `PUT`, `DELETE /projects/{id}` | Assinatura ativa |
| Listar / criar tarefas | `GET`, `POST /projects/{id}/tasks` | Assinatura ativa |
| Consultar / editar / excluir tarefa | `GET`, `PATCH`, `DELETE /tasks/{id}` | Assinatura ativa |

As listas aceitam `offset` (a partir de zero) e `limit` (de 1 a 100). Membros podem trabalhar em todos os projetos da sua empresa. Este MVP não tem permissões individuais por projeto.

## Como os dados ficam separados

O token assinado contém o usuário e a empresa. A API verifica assinatura, validade, emissor e destinatário e consulta o usuário novamente. Assim, a remoção de uma conta invalida seus próximos pedidos, e a função de administrador é sempre lida do banco.

Cada pedido cria sua própria sessão de banco. O SQLAlchemy acrescenta o filtro de empresa às consultas das entidades privadas e valida a empresa nas gravações. Cabeçalhos como `X-Tenant-ID` não escolhem a empresa, e campos inesperados no corpo são recusados.

No PostgreSQL, `users`, `projects` e `tasks` têm políticas de segurança por linha, chamadas RLS. A API define `app.tenant_id` apenas durante a transação. Mesmo uma consulta SQL sem filtro só enxerga as linhas da empresa definida. Sem contexto, essas tabelas não retornam dados. Uma chave estrangeira composta também impede associar uma tarefa ao projeto de outra empresa.

A conta da API não é superusuária, não pode ignorar RLS e não é dona das tabelas. A inicialização verifica essas condições e a presença de políticas. A tabela `tenants` pertence ao plano de controle: guarda cadastro, assinatura e contadores, tem acesso explícito pelo identificador autenticado e não usa RLS. O cadastro e a busca do identificador de empresa no login passam por esse plano de controle. Credenciais diretas de banco pertencem ao serviço, nunca aos clientes.

Referências: [segurança por linha no PostgreSQL](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) e [filtros globais no SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#sqlalchemy.orm.with_loader_criteria).

## Regras dos planos

| Plano | Usuários | Projetos | Requisições por mês |
| --- | ---: | ---: | ---: |
| Free | 2 | 3 | 100 |
| Pro | 10 | 50 | 10.000 |
| Business | 100 | 500 | 100.000 |

A cota de requisições é compartilhada pela empresa, contando acessos autenticados às rotas de projetos e tarefas. Um pedido admitido consome uma unidade mesmo que depois encontre um recurso inexistente. Pedidos recusados antes da reserva, inclusive validações do corpo, não consomem. Login, equipe, assinatura, documentação e monitoramento ficam fora dessa cota; assim, um administrador ainda consegue consultar o uso ou mudar de plano quando o limite acaba.

O contador reinicia no primeiro acesso de um novo mês, usando UTC. Excluir um projeto ou usuário libera uma vaga, mas não devolve requisições. O downgrade é recusado enquanto a empresa tiver mais usuários ou projetos do que o novo plano permite. Uma assinatura inativa bloqueia projetos, tarefas e novas contas, mas permite remover colegas e reativar o plano.

As operações que reservam requisições e vagas bloqueiam a linha da empresa no PostgreSQL. Isso evita que dois processos enxerguem a mesma vaga livre e ultrapassem o limite. Os pedidos da mesma empresa disputam essa linha; para volumes maiores, esse ponto merece medição e uma estratégia específica de contagem. Não há promessa de escala ilimitada neste MVP.

## Testes

Instale `requirements-dev.txt` no ambiente virtual e execute:

```sh
pytest -q
```

Os testes rápidos usam SQLite temporário. Eles verificam isolamento na aplicação, permissões, tokens, limites, assinatura e observabilidade. **SQLite não valida RLS nem os bloqueios do PostgreSQL**; os testes dessas garantias ficam explicitamente ignorados nesse modo.

Para rodar todos os testes em PostgreSQL, crie um banco separado, como `tenantflow_test`, e aplique a migração inicial com o dono do banco. Se já houver uma conta `tenantflow` no mesmo servidor, não execute novamente o `CREATE ROLE`: use outra instância dedicada ao teste ou retire apenas essa linha ao preparar o banco. Depois:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://tenantflow:local-demo-only@localhost:5432/tenantflow_test'
pytest -q
Remove-Item Env:TEST_DATABASE_URL
```

No Linux/macOS, use `TEST_DATABASE_URL='postgresql+psycopg://tenantflow:local-demo-only@localhost:5432/tenantflow_test' pytest -q`. Os testes criam empresas próprias e não limpam o banco; use um banco descartável. O GitHub Actions já prepara uma instância separada e roda os dois modos.

## O que observar

Cada resposta tem `X-Request-ID`. O log JSON registra esse identificador, a empresa autenticada, a rota, o status e a duração. Corpos, senhas, tokens e parâmetros da URL não são registrados. Rotas desconhecidas compartilham o rótulo `unmatched`, evitando criar uma série de métricas para cada endereço inventado.

O painel mostra requisições por segundo, erros do servidor, latência no percentil 95 e recusas por cota. As métricas agregam por rota, método e status; o uso individual da empresa é consultado em `/subscription`. Não há identificadores de empresas nos rótulos do Prometheus.

`/metrics` exige `Authorization: Bearer <METRICS_TOKEN>`. O Compose passa essa credencial para o Prometheus. Consulte a [documentação de configuração do Prometheus](https://prometheus.io/docs/prometheus/latest/configuration/configuration/) para ampliar a coleta.

## Decisões e próximos passos

FastAPI deixa os contratos da API e a documentação próximos do código. PostgreSQL acrescenta uma segunda barreira de isolamento. A assinatura simulada permite demonstrar as regras sem depender de um provedor de pagamentos.

Antes de publicar para usuários reais, o trabalho seguinte inclui recuperação de senha, confirmação de e-mail, limites específicos para cadastro e tentativas de login, integração de pagamento com eventos idempotentes, gestão de segredos, HTTPS, backups e migrações incrementais. O token expira em 60 minutos; este MVP não inclui renovação nem logout com revogação de token.

O Compose foi preparado para demonstração local. A suíte de testes e os detalhes da verificação realizada nesta entrega estão em `VALIDACAO.md`.

Uma descrição honesta para o currículo, após você explorar e entender a implementação:

> Desenvolvi uma API SaaS multiempresa com FastAPI e PostgreSQL, isolamento de dados por filtros de aplicação e políticas RLS, controle de planos e cotas transacionais, autenticação JWT e observabilidade com Prometheus e Grafana. Implementei testes de acesso cruzado e de concorrência para validar as regras de isolamento e uso.
