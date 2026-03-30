-- ============================================================
-- JobHunter Multi-Tenant Schema — PostgreSQL (Supabase)
-- Run this in Supabase SQL Editor before first deploy
-- ============================================================

-- ── USERS ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id             BIGINT PRIMARY KEY,  -- Telegram user_id
    first_name          TEXT    NOT NULL DEFAULT '',
    username            TEXT    DEFAULT NULL,

    -- BYOK: stored encrypted (AES-256 Fernet), never plaintext
    gemini_free_key     TEXT    DEFAULT NULL,
    gemini_paid_key     TEXT    DEFAULT NULL,  -- optional

    -- Career profile (populated via /update_profile)
    career_summary      TEXT    DEFAULT '',
    career_vectors      JSONB   DEFAULT NULL,   -- embeddings JSON

    -- State
    onboarding_step     TEXT    DEFAULT 'new', -- new | keys_set | profile_set | ready
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── JOBS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT    NOT NULL,
    user_id         BIGINT  NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- Core fields
    title           TEXT    NOT NULL,
    company         TEXT    NOT NULL,
    location        TEXT    DEFAULT '',
    url             TEXT    DEFAULT '',
    description     TEXT    DEFAULT '',
    source          TEXT    DEFAULT '',

    -- Scores
    rag_score       REAL    DEFAULT 0,
    llm_score       INTEGER DEFAULT 0,
    verdict         TEXT    DEFAULT '',  -- APPLY | MAYBE | SKIP
    seniority       TEXT    DEFAULT '',
    company_tier    TEXT    DEFAULT '',
    career_path     TEXT    DEFAULT '',
    fit_reason      TEXT    DEFAULT '',
    red_flags       TEXT    DEFAULT '',

    -- Tracking
    status          TEXT    DEFAULT 'NEW',  -- NEW | interested | applied | interviewing | rejected | skipped
    first_seen      TIMESTAMPTZ DEFAULT NOW(),
    last_seen       TIMESTAMPTZ DEFAULT NOW(),
    notified_at     TIMESTAMPTZ DEFAULT NULL,
    applied_at      TIMESTAMPTZ DEFAULT NULL,
    notes           TEXT    DEFAULT '',

    -- Generated docs
    cover_letter_text TEXT  DEFAULT '',
    cover_letter_pdf  BYTEA DEFAULT NULL,
    cv_pdf            BYTEA DEFAULT NULL,

    PRIMARY KEY (job_id, user_id)
);

-- ── INDEXES ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_jobs_user_id       ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status        ON jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_llm_score     ON jobs(user_id, llm_score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen    ON jobs(user_id, first_seen DESC);

-- ── ROW LEVEL SECURITY ───────────────────────────────────────
-- Users table: user can only see/edit their own row
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

CREATE POLICY users_self_access ON users
    USING (user_id = current_setting('app.current_user_id', TRUE)::BIGINT);

-- Jobs table: user can only see their own jobs
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;

CREATE POLICY jobs_tenant_isolation ON jobs
    USING (user_id = current_setting('app.current_user_id', TRUE)::BIGINT);

CREATE POLICY jobs_tenant_insert ON jobs
    FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', TRUE)::BIGINT);

-- ── ADMIN ROLE (bypasses RLS for migration/cron) ─────────────
-- The service role key from Supabase already has BYPASSRLS.
-- Use it ONLY in backend scripts, never expose to clients.

-- ── UPDATED_AT TRIGGER ───────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
