-- care-transition-agent schema. Every table that holds patient data carries tenant_id and is protected by row-level
-- security: the application connects, switches to the cta_app role and sets app.tenant for the transaction, so a query
-- that forgets its WHERE clause still sees one hospital's rows only. FORCE makes the policy apply to the table owner too.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cta_app') THEN
    CREATE ROLE cta_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tenants (
  id text PRIMARY KEY,
  name text NOT NULL,
  retention_days integer NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS cases (
  id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(id),
  external_ref text,
  status text NOT NULL DEFAULT 'open',
  as_of date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  identity_token text NOT NULL,
  identity_enc bytea NOT NULL,
  identity_nonce bytea NOT NULL,
  patient_sex text,
  retention_until date NOT NULL,
  purged_at timestamptz
);

CREATE TABLE IF NOT EXISTS documents (
  case_id text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  id text NOT NULL,
  tenant_id text NOT NULL,
  kind text NOT NULL,
  title text NOT NULL,
  authored_at timestamptz NOT NULL,
  author_role text,
  text_enc bytea,
  text_nonce bytea,
  pseudo_enc bytea,
  pseudo_nonce bytea,
  replacements jsonb NOT NULL DEFAULT '[]',
  injection_spans jsonb NOT NULL DEFAULT '[]',
  leak_kinds jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (case_id, id)
);

CREATE TABLE IF NOT EXISTS runs (
  id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  case_id text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  workflow text NOT NULL,
  status text NOT NULL,
  prompt text,
  prompt_version text,
  model text,
  upstream text,
  trace_id text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  input_tokens integer NOT NULL DEFAULT 0,
  output_tokens integer NOT NULL DEFAULT 0,
  model_calls integer NOT NULL DEFAULT 0,
  tool_calls integer NOT NULL DEFAULT 0,
  error text
);

CREATE TABLE IF NOT EXISTS run_steps (
  run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  seq integer NOT NULL,
  tenant_id text NOT NULL,
  kind text NOT NULL,          -- model | tool | guard
  name text NOT NULL,
  started_at timestamptz NOT NULL,
  duration_ms integer NOT NULL,
  input_tokens integer NOT NULL DEFAULT 0,
  output_tokens integer NOT NULL DEFAULT 0,
  status text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}',   -- never content: field names, statuses, counts
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS drafts (
  id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  case_id text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  run_id uuid REFERENCES runs(id),
  status text NOT NULL DEFAULT 'draft',  -- draft | released | discarded
  profile_version integer NOT NULL,
  prompt_version text,
  model text,
  created_at timestamptz NOT NULL DEFAULT now(),
  released_at timestamptz,
  released_by text,
  fhir jsonb
);

CREATE TABLE IF NOT EXISTS draft_fields (
  draft_id uuid NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  tenant_id text NOT NULL,
  field text NOT NULL,
  agent_value jsonb,
  agent_status text NOT NULL,     -- grounded | conflict | unsupported | ... | unknown | unknown_but_mentioned | missing
  reason text,
  evidence jsonb NOT NULL DEFAULT '[]',
  counter jsonb NOT NULL DEFAULT '[]',
  question text,
  review text NOT NULL DEFAULT 'pending',   -- pending | accepted | edited | rejected | answered
  final_value jsonb,
  reviewed_by text,
  reviewed_at timestamptz,
  PRIMARY KEY (draft_id, field)
);

CREATE TABLE IF NOT EXISTS review_events (
  id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  draft_id uuid NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  field text NOT NULL,
  action text NOT NULL,
  actor text NOT NULL,
  at timestamptz NOT NULL DEFAULT now(),
  agent_status text,
  agent_value jsonb,
  final_value jsonb,
  prompt_version text,
  model text,
  seconds_on_field real
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  case_id text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  run_id uuid REFERENCES runs(id),
  role text NOT NULL,
  text text NOT NULL,          -- pseudonymised; re-identified only for display
  citations jsonb NOT NULL DEFAULT '[]',
  status text NOT NULL DEFAULT 'ok',
  feedback text,
  at timestamptz NOT NULL DEFAULT now()
);

-- append-only audit trail, hash-chained per tenant
CREATE TABLE IF NOT EXISTS audit (
  id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  object text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}',
  prev_hash text NOT NULL,
  hash text NOT NULL
);

CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit is append-only';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_no_update ON audit;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit FOR EACH ROW EXECUTE FUNCTION audit_append_only();

-- prompt versions in service, per tenant ('*' = everyone) with a canary share
CREATE TABLE IF NOT EXISTS prompt_deployments (
  tenant_id text NOT NULL,
  prompt text NOT NULL,
  version text NOT NULL,
  model text NOT NULL,
  share real NOT NULL,
  since timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, prompt, version)
);

-- no patient data below: evaluation results on the synthetic golden set, and the provider network
CREATE TABLE IF NOT EXISTS eval_runs (
  id uuid PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL,
  candidate jsonb NOT NULL,
  baseline jsonb,
  metrics jsonb NOT NULL,
  gate jsonb,
  passed boolean
);

CREATE TABLE IF NOT EXISTS providers (
  id text PRIMARY KEY,
  name text NOT NULL,
  kind text NOT NULL,            -- care_type option
  region text NOT NULL,
  lat real NOT NULL,
  lon real NOT NULL,
  capabilities jsonb NOT NULL,   -- {"oxygen": true, "mre": ["mrsa"], ...}
  free_from date
);

CREATE TABLE IF NOT EXISTS provider_requests (
  id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  draft_id uuid REFERENCES drafts(id) ON DELETE CASCADE,
  provider_id text NOT NULL REFERENCES providers(id),
  rank integer NOT NULL,
  score real,
  features jsonb NOT NULL DEFAULT '{}',
  sent_at timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz,
  outcome text                    -- accepted | declined | none
);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['cases','documents','runs','run_steps','drafts','draft_fields','review_events','chat_messages','audit','provider_requests']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant'', true))', t);
  END LOOP;
END $$;

ALTER TABLE prompt_deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_deployments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_or_global ON prompt_deployments;
CREATE POLICY tenant_or_global ON prompt_deployments
  USING (tenant_id IN ('*', current_setting('app.tenant', true)))
  WITH CHECK (tenant_id IN ('*', current_setting('app.tenant', true)));

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cta_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cta_app;
REVOKE UPDATE, DELETE ON audit FROM cta_app;
