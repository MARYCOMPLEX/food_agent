-- Replayable fixture: legacy schema after scripts/migrate_turn_id.py runs.
DROP TABLE IF EXISTS search_results CASCADE;

CREATE TABLE IF NOT EXISTS search_results (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID UNIQUE NOT NULL,
    restaurants JSONB NOT NULL DEFAULT '[]',
    summary TEXT,
    filtered_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_results_session ON search_results(session_id);

ALTER TABLE search_results
ADD COLUMN IF NOT EXISTS turn_id INTEGER DEFAULT 1;

ALTER TABLE search_results
ADD COLUMN IF NOT EXISTS query TEXT;

ALTER TABLE search_results
DROP CONSTRAINT IF EXISTS search_results_session_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_results_session_turn
ON search_results(session_id, turn_id);

CREATE INDEX IF NOT EXISTS idx_results_turn
ON search_results(session_id, turn_id DESC);
