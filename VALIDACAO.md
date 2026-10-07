# Verificação da entrega

Verificado em 7 de outubro de 2026, com Python 3.12 e PostgreSQL 17.11 no Windows.

## Resultado

- **19 testes passaram no PostgreSQL real**, usando a conta restrita `tenantflow`.
- O conjunto rápido em SQLite verifica a aplicação; cinco testes específicos de PostgreSQL ficam ignorados nesse modo.
- A migração inicial foi aplicada com sucesso em um banco novo. A conta usada pela API não é dona das tabelas, não é superusuária e não ignora RLS.
- Consultas SQL diretas não conseguiram ler, alterar ou excluir o projeto de outra empresa. Uma tentativa de inserir dados com a empresa errada foi recusada pelo banco.
- O contexto da empresa desapareceu ao encerrar a transação, evitando que fosse reaproveitado pelo próximo pedido.
- Com uma requisição disponível na cota, oito pedidos simultâneos produziram um sucesso e sete respostas 429.
- Com uma vaga de projeto disponível, seis criações simultâneas produziram um sucesso e cinco recusas.
- Com uma vaga de usuário disponível, cinco criações simultâneas produziram um sucesso e quatro recusas.
- A API iniciou com Uvicorn e respondeu por HTTP. Saúde, OpenAPI e documentação interativa foram consultados.
- `scripts/demo.py` criou duas empresas, um projeto e uma tarefa, confirmou a resposta 404 no acesso cruzado e simulou a mudança de plano.
- As dependências instaladas passaram pela verificação de compatibilidade.

## Limites desta verificação

Docker não estava instalado neste ambiente. O Compose e os arquivos de provisionamento foram revisados e verificados como YAML/JSON, mas os contêineres do Prometheus e Grafana não foram iniciados. A coleta e a aparência do painel precisam ser confirmadas quando você executar `docker compose up --build -d`.

A biblioteca de testes emitiu um aviso de depreciação sobre o uso de httpx pelo TestClient. Os testes passaram; uma futura atualização desse cliente merece revisão das dependências de desenvolvimento.

O PostgreSQL e a API usados nesta verificação eram temporários e foram encerrados ao terminar. Nenhum serviço foi publicado.
