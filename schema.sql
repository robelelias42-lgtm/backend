-- Marageli (ማራጌሊ) database schema
-- Run this once against your Turso database to set up all tables.

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    full_name TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

-- Starter categories
INSERT OR IGNORE INTO categories (name) VALUES
    ('Cosmetics'),
    ('Electronics'),
    ('Clothes'),
    ('Shoes'),
    ('Books'),
    ('Accessories'),
    ('Other');

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    title TEXT NOT NULL,
    description TEXT,
    price_etb REAL NOT NULL,
    photo_file_id TEXT,
    pickup_location TEXT,
    is_store_item INTEGER NOT NULL DEFAULT 0,      -- 1 = your own Marageli Store item, 0 = student listing
    status TEXT NOT NULL DEFAULT 'draft',           -- draft -> pending_payment -> pending_review -> approved / rejected / sold
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    receipt_file_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',         -- pending -> approved / rejected
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    buyer_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'requested',       -- requested -> confirmed -> completed / cancelled
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL REFERENCES users(id),
    listing_id INTEGER REFERENCES listings(id),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, listing_id)
);

CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    reaction TEXT NOT NULL CHECK (reaction IN ('like', 'dislike')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, listing_id)
);

CREATE TABLE IF NOT EXISTS game_boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'closed', -- 'closed' = waiting for winners, 'open' = accepting picks
    price_etb REAL NOT NULL DEFAULT 20,
    round INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS game_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL REFERENCES game_boards(id),
    number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'available', -- available | pending_payment | taken
    user_id INTEGER REFERENCES users(id),
    receipt_file_id TEXT,
    taken_at TEXT,
    UNIQUE(board_id, number)
);

INSERT OR IGNORE INTO game_boards (name) VALUES ('Tepi'), ('Aman'), ('Mizan');
