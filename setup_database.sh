#!/bin/bash
# Low-bandwidth way to set up your Marageli database — one HTTPS request,
# no CLI install needed. Just needs curl, which is already on your computer.
#
# 1. Fill in your real values below (between the quotes).
# 2. Run:  bash setup_database.sh

TURSO_HTTP_URL="https://marageli-robelelias42-lgtm.aws-ap-south-1.turso.io/v2/pipeline"
TURSO_AUTH_TOKEN="eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODk1MTcxNzgsImlkIjoiMDFhMGE3NTMtZGIwMS03MjlkLWFiNDYtOGVhYWY5MDkzNDE1Iiwia2lkIjoidzBTSWRmek9UVkg2VWZ5ZWVaemFaQmFlS1FJREROR01CaDRBYzZXZ2pFQSIsInJpZCI6IjY4OTNjZTAzLTAzZmYtNGVkYi05OTI0LTRhY2Y5MGNkN2FhNiJ9.2QTqDVyleSPRBeJw9AthQfi4lWGZLW2BaFZY6_wRRcD50Rt7qaE25es6Yql5xJ00umq9ytK0wctPqo1KiQdOBQ"

curl -s -X POST "$TURSO_HTTP_URL" \
  -H "Authorization: Bearer $TURSO_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "requests": [
      { "type": "execute", "stmt": { "sql": "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER UNIQUE NOT NULL, username TEXT, full_name TEXT, is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')))" } },
      { "type": "execute", "stmt": { "sql": "CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)" } },
      { "type": "execute", "stmt": { "sql": "INSERT OR IGNORE INTO categories (name) VALUES ('Cosmetics')" } },
      { "type": "execute", "stmt": { "sql": "INSERT OR IGNORE INTO categories (name) VALUES ('Electronics')" } },
      { "type": "execute", "stmt": { "sql": "INSERT OR IGNORE INTO categories (name) VALUES ('Clothes')" } },
      { "type": "execute", "stmt": { "sql": "INSERT OR IGNORE INTO categories (name) VALUES ('Shoes')" } },
      { "type": "execute", "stmt": { "sql": "INSERT OR IGNORE INTO categories (name) VALUES ('Books')" } },
      { "type": "execute", "stmt": { "sql": "INSERT OR IGNORE INTO categories (name) VALUES ('Accessories')" } },
      { "type": "execute", "stmt": { "sql": "INSERT OR IGNORE INTO categories (name) VALUES ('Other')" } },
      { "type": "execute", "stmt": { "sql": "CREATE TABLE IF NOT EXISTS listings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), category_id INTEGER NOT NULL REFERENCES categories(id), title TEXT NOT NULL, description TEXT, price_etb REAL NOT NULL, photo_file_id TEXT, pickup_location TEXT, is_store_item INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL DEFAULT (datetime('now')), reviewed_at TEXT)" } },
      { "type": "execute", "stmt": { "sql": "CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listings(id), receipt_file_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', submitted_at TEXT NOT NULL DEFAULT (datetime('now')), reviewed_at TEXT)" } },
      { "type": "execute", "stmt": { "sql": "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listings(id), buyer_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'requested', created_at TEXT NOT NULL DEFAULT (datetime('now')))" } },
      { "type": "execute", "stmt": { "sql": "CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL REFERENCES users(id), listing_id INTEGER REFERENCES listings(id), reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')))" } },
      { "type": "execute", "stmt": { "sql": "SELECT name FROM categories" } },
      { "type": "close" }
    ]
  }'
echo ""
echo "Done. Look for the category names (Cosmetics, Electronics, etc.) in the output above — that confirms it worked."
