-- Users
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    telegram_id TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sessions
CREATE TABLE sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    token TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Records
CREATE TABLE records (
    id BIGSERIAL PRIMARY KEY,
    image_type TEXT NOT NULL DEFAULT 'unknown',
    amount DOUBLE PRECISION,
    currency TEXT DEFAULT 'VND',
    sender TEXT,
    receiver TEXT,
    transaction_id TEXT,
    order_id TEXT,
    platform TEXT,
    raw_text TEXT,
    confidence DOUBLE PRECISION DEFAULT 0,
    image_path TEXT,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notes
CREATE TABLE notes (
    id BIGSERIAL PRIMARY KEY,
    record_id BIGINT REFERENCES records(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Orders (share bill)
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    record_id BIGINT REFERENCES records(id) ON DELETE CASCADE,
    telegram_id TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_records_type ON records(image_type);
CREATE INDEX idx_records_created ON records(created_at DESC);
CREATE INDEX idx_notes_record ON notes(record_id);
CREATE INDEX idx_orders_record ON orders(record_id);
CREATE INDEX idx_sessions_token ON sessions(token);

-- RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all" ON users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON sessions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON records FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON notes FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON orders FOR ALL USING (true) WITH CHECK (true);
