PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL CHECK (channel IN ('messenger', 'demo')),
    channel_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(channel, channel_user_id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'needs_human', 'whatsapp_consent_pending', 'transferred', 'closed')),
    intent TEXT,
    processing_status TEXT NOT NULL DEFAULT 'pending',
    last_inbound_at TEXT,
    consent_prompt_message_id TEXT,
    consent_prompt_at TEXT,
    whatsapp_consent_message_id TEXT,
    whatsapp_consent_at TEXT,
    whatsapp_declined_message_id TEXT,
    whatsapp_declined_at TEXT,
    handoff_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_status_updated_idx ON conversations(status, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    channel_message_id TEXT UNIQUE,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    body TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'received'
        CHECK (delivery_status IN ('received', 'sent', 'draft', 'failed')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation_created_idx ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id) ON DELETE CASCADE,
    score INTEGER NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'interested', 'qualified')),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS opportunities_status_updated_idx ON opportunities(status, updated_at);

CREATE TABLE IF NOT EXISTS service_catalog (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    language TEXT NOT NULL CHECK (language IN ('ar', 'en')),
    keywords_json TEXT NOT NULL,
    approved_answer TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS service_catalog_language_active_idx ON service_catalog(language, active);
