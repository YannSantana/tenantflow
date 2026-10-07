-- Executado pelo dono do banco, nunca pela conta usada pela API.
BEGIN;
CREATE ROLE tenantflow LOGIN PASSWORD 'local-demo-only' NOSUPERUSER NOBYPASSRLS;
CREATE TABLE tenants (
    id varchar(36) PRIMARY KEY,
    name varchar(120) NOT NULL,
    slug varchar(60) NOT NULL UNIQUE,
    plan varchar(20) NOT NULL CHECK (plan IN ('free','pro','business')),
    status varchar(20) NOT NULL CHECK (status IN ('active','canceled','expired')),
    usage_month varchar(7) NOT NULL,
    requests_used integer NOT NULL CHECK (requests_used >= 0)
);
CREATE TABLE users (
    id varchar(36) PRIMARY KEY,
    tenant_id varchar(36) NOT NULL REFERENCES tenants(id),
    email varchar(254) NOT NULL,
    password_hash varchar(255) NOT NULL,
    role varchar(20) NOT NULL CHECK (role IN ('admin','member')),
    UNIQUE (tenant_id, email)
);
CREATE INDEX ix_users_tenant_id ON users(tenant_id);
CREATE TABLE projects (
    id varchar(36) PRIMARY KEY,
    tenant_id varchar(36) NOT NULL REFERENCES tenants(id),
    name varchar(120) NOT NULL,
    description varchar(1000) NOT NULL,
    UNIQUE (tenant_id, id)
);
CREATE INDEX ix_projects_tenant_id ON projects(tenant_id);
CREATE TABLE tasks (
    id varchar(36) PRIMARY KEY,
    tenant_id varchar(36) NOT NULL REFERENCES tenants(id),
    project_id varchar(36) NOT NULL,
    title varchar(160) NOT NULL,
    done boolean NOT NULL,
    FOREIGN KEY (tenant_id, project_id) REFERENCES projects(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX ix_tasks_tenant_id ON tasks(tenant_id);
CREATE INDEX ix_tasks_project_id ON tasks(project_id);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON users TO tenantflow
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_isolation ON projects TO tenantflow
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_isolation ON tasks TO tenantflow
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO tenantflow;
GRANT SELECT, INSERT, UPDATE ON tenants TO tenantflow;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, projects, tasks TO tenantflow;
COMMIT;
