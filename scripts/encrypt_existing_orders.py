import os, sqlite3
from cryptography.fernet import Fernet

DB = os.path.join(os.path.dirname(__file__), "..", "store.db")
KEY = os.environ.get("DATA_ENC_KEY")
if not KEY:
    raise SystemExit("Set DATA_ENC_KEY env var before running this script.")

fernet = Fernet(KEY.encode())

FIELDS = ["agency","authorized_officer","position_clearance","contact_number","po_number","contract_reference","funding_source","delivery_location","payment_method"]

def looks_encrypted(v):
    return isinstance(v, str) and v.startswith("gAAAAA")

conn = sqlite3.connect(DB)
cur = conn.cursor()
rows = cur.execute("SELECT id, " + ", ".join(FIELDS) + " FROM orders").fetchall()
for row in rows:
    order_id = row[0]
    updates = {}
    for idx, f in enumerate(FIELDS, start=1):
        val = row[idx]
        if val and not looks_encrypted(val):
            enc = fernet.encrypt(val.encode()).decode()
            updates[f] = enc
    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [order_id]
        cur.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", params)
        print("Encrypted order", order_id, "fields:", ", ".join(updates.keys()))
conn.commit()
conn.close()
print("Done")