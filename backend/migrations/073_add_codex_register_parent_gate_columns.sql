ALTER TABLE codex_register_accounts
    ADD COLUMN IF NOT EXISTS plan_type TEXT,
    ADD COLUMN IF NOT EXISTS organization_id TEXT,
    ADD COLUMN IF NOT EXISTS workspace_reachable BOOLEAN,
    ADD COLUMN IF NOT EXISTS members_page_accessible BOOLEAN,
    ADD COLUMN IF NOT EXISTS codex_register_role TEXT;

CREATE INDEX IF NOT EXISTS idx_codex_register_accounts_role_created_at
    ON codex_register_accounts (codex_register_role, created_at DESC);
