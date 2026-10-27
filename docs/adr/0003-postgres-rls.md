# 0003: Tenant isolation in PostgreSQL row-level security

**Decision.** Every table with patient data carries `tenant_id` and a `FORCE`d row-level-security policy on
`current_setting('app.tenant')`. The application switches to a role without `BYPASSRLS` for each transaction.

**Why.** A forgotten `WHERE tenant_id = …` is the most likely way one hospital sees another's patients. With RLS the
database refuses it. The superuser used by migrations would bypass RLS, which is why the switch to the application
role is explicit and tested.
