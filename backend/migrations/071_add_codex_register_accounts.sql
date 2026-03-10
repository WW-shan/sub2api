CREATE TABLE IF NOT EXISTS codex_register_accounts (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    password TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    access_token TEXT NOT NULL,
    account_id TEXT,
    source TEXT NOT NULL DEFAULT 'codex-register',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (email, source)
);

CREATE INDEX IF NOT EXISTS idx_codex_register_accounts_created_at
    ON codex_register_accounts (created_at DESC);
