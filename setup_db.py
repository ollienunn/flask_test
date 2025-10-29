import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "store.db"

PRODUCTS = [
    ("F35",   "F-35 Lightning II", "Stealth multirole fighter with advanced sensor fusion.", 250_000_000.0, "images/f35.gif"),
    ("FA18",  "F/A-18 Hornet", "Carrier-capable multirole combat aircraft.", 185_000_000.0, "images/F18-Super-Hornet.png"),
    ("GROWLER","EA-18G Growler", "Electronic attack variant for suppression of enemy air defenses.", 195_000_000.0, "images/growler.webp"),
    ("B2",    "B-2 Spirit", "Stealth strategic bomber with flying-wing design.", 2_000_000_000.0, "images/b2.png"),
    ("AC130", "AC-130 Spectre", "A massive plane that provides close air support and precision firepower to ensure operational success.", 200_000_000.0, "images/ac-130a.webp"),
]

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    price REAL NOT NULL,
    image TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    address TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS donations (
    id INTEGER PRIMARY KEY,
    donor TEXT,
    amount REAL NOT NULL,
    card_last4 TEXT,
    created_at TEXT NOT NULL
);
"""

def recreate_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted existing DB: {DB_PATH}")
    else:
        print(f"No existing DB to delete at: {DB_PATH}")

def create_schema_and_seed(conn):
    now = datetime.utcnow().isoformat()
    conn.executescript(SCHEMA)
    # upsert products so running script multiple times keeps DB consistent
    for sku, name, desc, price, img in PRODUCTS:
        conn.execute("""
            INSERT INTO products (sku, name, description, price, image, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
              name=excluded.name,
              description=excluded.description,
              price=excluded.price,
              image=excluded.image
        """, (sku, name, desc, price, img, now))

def summary(conn):
    cur = conn.execute("SELECT COUNT(*) FROM products"); print("products:", cur.fetchone()[0])
    cur = conn.execute("SELECT COUNT(*) FROM customers"); print("customers:", cur.fetchone()[0])
    cur = conn.execute("SELECT COUNT(*) FROM orders"); print("orders:", cur.fetchone()[0])
    cur = conn.execute("SELECT COUNT(*) FROM order_items"); print("order_items:", cur.fetchone()[0])
    cur = conn.execute("SELECT COUNT(*) FROM donations"); print("donations:", cur.fetchone()[0])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Delete existing DB and recreate")
    args = p.parse_args()

    if args.force:
        recreate_db()

    created = not DB_PATH.exists()
    conn = sqlite3.connect(DB_PATH)
    try:
        create_schema_and_seed(conn)
        conn.commit()
        print(f"Database: {DB_PATH} {'created' if created else 'updated'}")
        summary(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()