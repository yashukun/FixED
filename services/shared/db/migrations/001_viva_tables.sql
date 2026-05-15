-- Viva feature schema migration.
-- This project currently uses Base.metadata.create_all for table creation.
-- Keep this SQL for explicit/manual migration workflows.

CREATE TABLE IF NOT EXISTS viva_sessions (
    id UUID PRIMARY KEY,
    file_id VARCHAR(255) NOT NULL,
    topic TEXT NOT NULL,
    chapter_number INTEGER NULL,
    question_count INTEGER NOT NULL DEFAULT 5,
    per_question_limit_seconds INTEGER NOT NULL DEFAULT 60,
    session_limit_seconds INTEGER NOT NULL DEFAULT 600,
    status VARCHAR(64) NOT NULL DEFAULT 'pending',
    warning_count INTEGER NOT NULL DEFAULT 0,
    current_question_index INTEGER NOT NULL DEFAULT 0,
    reference_photo_b64 TEXT NULL,
    started_at TIMESTAMP NULL,
    finished_at TIMESTAMP NULL,
    termination_reason VARCHAR(128) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_viva_sessions_file_created_at ON viva_sessions (file_id, created_at);

CREATE TABLE IF NOT EXISTS viva_questions (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,
    question_order INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    expected_points_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    asked_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_viva_questions_session_order ON viva_questions (session_id, question_order);

CREATE TABLE IF NOT EXISTS viva_turns (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,
    question_id UUID NOT NULL,
    answer_transcript TEXT NOT NULL DEFAULT '',
    answer_audio_b64 TEXT NULL,
    score NUMERIC(6, 2) NOT NULL DEFAULT 0,
    max_score NUMERIC(6, 2) NOT NULL DEFAULT 10,
    strengths_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    weaknesses_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    feedback TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_viva_turns_session_created_at ON viva_turns (session_id, created_at);

CREATE TABLE IF NOT EXISTS viva_proctor_events (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,
    event_type VARCHAR(64) NOT NULL DEFAULT 'frame_check',
    is_present INTEGER NOT NULL DEFAULT 1,
    is_match INTEGER NOT NULL DEFAULT 1,
    confidence NUMERIC(5, 4) NOT NULL DEFAULT 1,
    warning_count INTEGER NOT NULL DEFAULT 0,
    action VARCHAR(64) NOT NULL DEFAULT 'ok',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_viva_proctor_session_created_at ON viva_proctor_events (session_id, created_at);

CREATE TABLE IF NOT EXISTS viva_results (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL UNIQUE,
    overall_score NUMERIC(6, 2) NOT NULL DEFAULT 0,
    max_score NUMERIC(6, 2) NOT NULL DEFAULT 0,
    strengths_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    weak_areas_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    question_breakdown_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_viva_results_created_at ON viva_results (created_at);
