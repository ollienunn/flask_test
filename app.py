from flask import Flask, render_template, g, request, redirect, url_for, jsonify, session, flash, render_template_string
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import os
import re
from werkzeug.utils import secure_filename
import smtplib
import ssl
from email.message import EmailMessage
from flask import current_app
from flask import g, send_from_directory, abort
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import json
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "store.db"
PRIVATE_UPLOADS = Path(__file__).parent / "private_uploads"
PRIVATE_UPLOADS.mkdir(parents=True, exist_ok=True)

app.secret_key = os.environ.get("FLASK_SECRET", "CheeseSauce")

load_dotenv()  # optional: loads .env into os.environ for local dev

# DATA_ENC_KEY should be a base64 Fernet key (you already set it with setx)
DATA_ENC_KEY = os.environ.get("DATA_ENC_KEY")
fernet = Fernet(DATA_ENC_KEY.encode()) if DATA_ENC_KEY else None

def encrypt_field(plaintext):
    """Return Fernet token (str) or None if not available/empty."""
    if not plaintext or fernet is None:
        return None
    return fernet.encrypt(str(plaintext).encode()).decode()

def decrypt_field(token):
    """Return decrypted plaintext (str) or None on failure."""
    if not token or fernet is None:
        return None
    return fernet.decrypt(token.encode()).decode()

# simple login_required decorator (admin-only)
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return wrapped

# Admin login/logout routes
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        return render_template("admin_login.html")
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
    ADMIN_PASS = os.environ.get("ADMIN_PASS", "password")
    if username == ADMIN_USER and password == ADMIN_PASS:
        session["is_admin"] = True
        session["admin_user"] = username
        session.permanent = False
        session["last_active"] = datetime.now(timezone.utc).timestamp()
        session["created_at"] = datetime.now(timezone.utc).timestamp()
        next_url = request.args.get("next") or url_for("admin_products")
        return redirect(next_url)
    return redirect(url_for("admin_login"))

@app.route("/admin/logout")
def admin_logout():
    # fully clear session on admin logout to avoid stale flags
    session.clear()
    flash("Admin logged out.", "info")
    return redirect(url_for("index"))

def get_db():
    """Return a sqlite3.Connection (row factory set) stored in flask.g"""
    if 'db' not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def get_products(limit=None):
    db = get_db()
    sql = "SELECT id, sku, name, description, price, image, stock FROM products ORDER BY id"
    cur = db.execute(sql) if not limit else db.execute(sql + " LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]

@app.route("/")
def index():
    featured = get_products(limit=3)
    return render_template("index.html", featured=featured)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/products")
def products():
    prods = get_products()
    return render_template("products.html", products=prods)

# admin: list & update products (POST from each product card)
@app.route("/admin/products", methods=["GET", "POST"])
@login_required
def admin_products():
    db = get_db()
    if request.method == "POST":
        sku = (request.form.get("sku") or "").strip()
        if not sku:
            return redirect(url_for("admin_products"))

        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        price_raw = (request.form.get("price") or "").replace(",", "").strip()
        stock_raw = (request.form.get("stock") or "").strip()
        try:
            price_val = float(price_raw) if price_raw != "" else None
        except ValueError:
            price_val = None
        try:
            stock_val = int(stock_raw) if stock_raw != "" else None
        except ValueError:
            stock_val = None

        image_file = request.files.get("image")
        image_path = None
        if image_file and image_file.filename:
            images_dir = Path(__file__).parent / "static" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            filename = secure_filename(image_file.filename)
            dest = images_dir / filename
            image_file.save(str(dest))
            image_path = f"images/{filename}"

        # build update based on provided fields
        params = []
        set_parts = []
        if name != "":
            set_parts.append("name = ?"); params.append(name)
        if description != "":
            set_parts.append("description = ?"); params.append(description)
        if price_val is not None:
            set_parts.append("price = ?"); params.append(price_val)
        if stock_val is not None:
            set_parts.append("stock = ?"); params.append(stock_val)
        if image_path:
            set_parts.append("image = ?"); params.append(image_path)

        if set_parts:
            sql = "UPDATE products SET " + ", ".join(set_parts) + " WHERE sku = ?"
            params.append(sku)
            try:
                db.execute(sql, params)
                db.commit()
            except Exception:
                db.rollback()
        return redirect(url_for("admin_products"))

    products = get_products()
    return render_template("edit_products.html", products=products)

# helpers for adding new products
def _make_sku_candidate(name):
    cand = re.sub(r'[^A-Za-z0-9]+', '-', (name or '').strip()).strip('-').upper()
    if not cand:
        cand = 'SKU'
    return cand[:30]

def _unique_sku(db, base):
    sku = base
    suffix = 1
    while True:
        cur = db.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone()
        if not cur:
            return sku
        sku = f"{base[:24]}-{suffix}"
        suffix += 1

# admin add product: accept stock
@app.route("/admin/products/add", methods=["POST"])
@login_required
def admin_add_product():
    db = get_db()
    name = (request.form.get("name") or "").strip()
    sku = (request.form.get("sku") or "").strip().upper()
    description = (request.form.get("description") or "").strip()
    price_raw = (request.form.get("price") or "").replace(",", "").strip()
    stock_raw = (request.form.get("stock") or "").strip()
    try:
        price_val = float(price_raw) if price_raw != "" else 0.0
    except ValueError:
        price_val = 0.0
    try:
        stock_val = int(stock_raw) if stock_raw != "" else 0
    except ValueError:
        stock_val = 0

    image_file = request.files.get("image")
    image_path = None
    if image_file and image_file.filename:
        images_dir = Path(__file__).parent / "static" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(image_file.filename)
        dest = images_dir / filename
        image_file.save(str(dest))
        image_path = f"images/{filename}"

    if not sku:
        base = _make_sku_candidate(name)
        sku = _unique_sku(db, base)
    else:
        sku = _unique_sku(db, sku.upper())

    created_at = datetime.utcnow().isoformat()
    try:
        db.execute(
            "INSERT INTO products (sku, name, description, price, image, stock, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sku, name, description, price_val, image_path, stock_val, created_at)
        )
        db.commit()
    except Exception:
        db.rollback()
    return redirect(url_for("admin_products"))

@app.route("/admin/products/delete", methods=["POST"])
@login_required
def admin_delete_product():
    db = get_db()
    sku = (request.form.get("sku") or "").strip()
    if not sku:
        return redirect(url_for("admin_products"))

    cur = db.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
    if not cur:
        return redirect(url_for("admin_products"))

    product_id = cur["id"]
    # prevent deletion when referenced by order_items
    ref = db.execute("SELECT COUNT(*) AS cnt FROM order_items WHERE product_id = ?", (product_id,)).fetchone()
    if ref and ref["cnt"] > 0:
        return redirect(url_for("admin_products", error="in_use"))

    try:
        db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        db.commit()
    except Exception:
        db.rollback()
    return redirect(url_for("admin_products"))

def _ensure_order_columns(conn):
    """
    Add government-specific columns to orders table if they don't exist.
    Safe to run multiple times.
    """
    cur = conn.execute("PRAGMA table_info(orders)").fetchall()
    cols = { r[1] for r in cur }
    additions = {
        "agency": "TEXT",
        "authorized_officer": "TEXT",
        "official_email": "TEXT",
        "position_clearance": "TEXT",
        "contact_number": "TEXT",
        "po_number": "TEXT",
        "contract_reference": "TEXT",
        "funding_source": "TEXT",
        "auth_doc": "TEXT",
        "vendor_id": "TEXT",
        "end_user_cert": "TEXT",
        "export_license_status": "TEXT",
        "delivery_location": "TEXT",
        "required_delivery_date": "TEXT",
        "payment_method": "TEXT",
        "declaration_agreed": "INTEGER",
        "digital_signature": "TEXT"
    }
    for name, sqltype in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {sqltype};")

def _ensure_schema_startup():
    """Run once at startup to ensure orders/table and carts/password columns exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_order_columns(conn)
        # ensure customers table has a password column (safe to run multiple times)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'").fetchone()
        if cur:
            cols = { r[1] for r in conn.execute("PRAGMA table_info(customers)").fetchall() }
            if "password" not in cols:
                conn.execute("ALTER TABLE customers ADD COLUMN password TEXT;")
        # ensure carts table exists to persist per-customer cart JSON
        conn.execute("""
            CREATE TABLE IF NOT EXISTS carts (
                customer_id INTEGER PRIMARY KEY,
                cart TEXT,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            );
        """)
        conn.commit()
    finally:
        conn.close()

# Cart persistence helpers
def load_customer_cart(customer_id):
    db = get_db()
    row = db.execute("SELECT cart FROM carts WHERE customer_id = ?", (customer_id,)).fetchone()
    if not row or not row["cart"]:
        return {}
    try:
        return json.loads(row["cart"])
    except Exception:
        return {}

def save_customer_cart(customer_id, cart_dict):
    db = get_db()
    data = json.dumps(cart_dict or {})
    cur = db.execute("SELECT 1 FROM carts WHERE customer_id = ?", (customer_id,)).fetchone()
    if cur:
        db.execute("UPDATE carts SET cart = ? WHERE customer_id = ?", (data, customer_id))
    else:
        db.execute("INSERT INTO carts (customer_id, cart) VALUES (?, ?)", (customer_id, data))
    db.commit()

def merge_carts(session_cart, stored_cart):
    """Merge two cart dicts {sku: qty} — session wins for additive quantities."""
    out = dict(stored_cart or {})
    for sku, qty in (session_cart or {}).items():
        try:
            q = int(qty)
        except Exception:
            q = 0
        if q <= 0:
            continue
        out[sku] = out.get(sku, 0) + q
    return out

def save_cart_if_logged_in():
    """Call after mutating session['cart'] to persist for logged-in customers."""
    cust_id = session.get("customer_id")
    if cust_id:
        save_customer_cart(cust_id, session.get("cart", {}) or {})

# --- Auth routes: register / login / logout ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    if not email or not password or not name:
        flash("Name, email and password required.", "danger")
        return redirect(url_for("register"))
    db = get_db()
    if db.execute("SELECT id FROM customers WHERE email = ?", (email,)).fetchone():
        flash("Account already exists for that email.", "warning")
        return redirect(url_for("login"))
    pw_hash = generate_password_hash(password)
    created_at = datetime.utcnow().isoformat()
    cur = db.execute("INSERT INTO customers (name, email, created_at, password) VALUES (?, ?, ?, ?)",
                     (name, email, created_at, pw_hash))
    db.commit()
    session["customer_id"] = cur.lastrowid
    session["customer_name"] = name
    session.permanent = False
    session["last_active"] = datetime.now(timezone.utc).timestamp()
    session["created_at"] = datetime.now(timezone.utc).timestamp()
    # if there is a session cart, save it to DB
    if session.get("cart"):
        save_customer_cart(session["customer_id"], session["cart"])
    flash("Registration complete. Logged in.", "success")
    return redirect(url_for("products"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    db = get_db()
    row = db.execute("SELECT id, name, password FROM customers WHERE email = ?", (email,)).fetchone()
    logger.debug("Login attempt for email=%s found_row=%s", email, bool(row))
    if not row:
        flash("Invalid email or password.", "danger")
        return redirect(url_for("login"))
    if not row["password"]:
        logger.debug("Account %s has no password set", email)
        flash("Invalid email or password.", "danger")
        return redirect(url_for("login"))
    ok = check_password_hash(row["password"], password)
    logger.debug("Password check for %s: %s", email, ok)
    if not ok:
        flash("Invalid email or password.", "danger")
        return redirect(url_for("login"))
    # login success — merge session cart with stored cart and persist
    stored = load_customer_cart(row["id"])
    sess_cart = session.get("cart", {}) or {}
    merged = merge_carts(sess_cart, stored)
    session["customer_id"] = row["id"]
    session["customer_name"] = row["name"]
    session.permanent = False
    session["last_active"] = datetime.now(timezone.utc).timestamp()
    session["created_at"] = datetime.now(timezone.utc).timestamp()
    session["cart"] = merged
    save_customer_cart(row["id"], merged)
    logger.debug("Login success, session keys: %s", list(session.keys()))
    flash("Logged in.", "success")
    return redirect(url_for("products"))

@app.route("/logout")
def logout():
    # fully clear session on customer logout
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("products"))

# -- Cart helpers ------------------------------------------------
def _cart_get():
    return session.setdefault("cart", {})  # { sku: qty }

def _cart_set(cart):
    session["cart"] = cart
    session.modified = True

# -- Add to cart -------------------------------------------------
@app.route("/cart/add", methods=["POST"])
def cart_add():
    sku = (request.form.get("sku") or "").strip().upper()
    try:
        qty = int(request.form.get("qty") or 1)
    except ValueError:
        qty = 1
    if qty < 1:
        qty = 1

    db = get_db()
    prod = db.execute("SELECT sku, stock FROM products WHERE sku = ?", (sku,)).fetchone()
    if not prod:
        flash("Product not found.", "danger")
        return redirect(request.referrer or url_for("products"))

    # don't add more than stock
    available = prod["stock"] or 0
    cart = _cart_get()
    current = cart.get(sku, 0)
    desired = current + qty
    if desired > available:
        flash(f"Only {available} units available for {sku}.", "warning")
        # set to max available
        cart[sku] = available
    else:
        cart[sku] = desired
    _cart_set(cart)
    # persist for logged-in customers
    save_cart_if_logged_in()
    flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("products"))

@app.route("/cart")
def cart_view():
    """Render customer's cart (used by navbar link)."""
    cart = session.get("cart", {}) or {}
    db = get_db()
    items = []
    total = 0.0

    if cart:
        placeholders = ",".join("?" for _ in cart.keys())
        rows = db.execute(f"SELECT id, sku, name, price, image, stock FROM products WHERE sku IN ({placeholders})", tuple(cart.keys())).fetchall()
        prod_map = {r["sku"]: dict(r) for r in rows}
        for sku, qty in cart.items():
            p = prod_map.get(sku)
            if not p:
                continue
            try:
                q = int(qty)
            except Exception:
                q = 0
            subtotal = (p.get("price") or 0.0) * q
            total += subtotal
            items.append({
                "sku": sku,
                "id": p.get("id"),
                "name": p.get("name"),
                "price": p.get("price") or 0.0,
                "qty": q,
                "stock": p.get("stock") or 0,
                "subtotal": subtotal,
                "image": p.get("image")
            })

    return render_template("cart.html", items=items, total=total)


TEACHER_EGG_CODE = os.environ.get("TEACHER_EGG_CODE", "Fonganator")

@app.route("/easter-egg", methods=["GET"])
def easter_egg():
    """
    Hidden easter-egg: teacher can visit /easter-egg?code=<secret>
    If the code matches TEACHER_EGG_CODE, mark session and show a small secret message.
    Returns 404 when code is not provided or incorrect to remain hidden.
    """
    code = (request.args.get("code") or "").strip()
    if not code or code != TEACHER_EGG_CODE:
        # intentionally return 404 so the endpoint is stealthy
        return ("", 404)

    # mark found in session so pages can optionally show a badge for the teacher
    session["found_easter_egg"] = True
    secret_html = """
    <!doctype html>
    <html lang="en"><head><meta charset="utf-8"><title>Secret Found</title>
    <style>body{font-family:system-ui,Segoe UI,Roboto,Arial;margin:48px;color:#0b3d2e} .box{border:2px dashed #9db89a;padding:24px;border-radius:8px;background:#f6fbf2}</style>
    </head><body>
    <div class="box">
      <h2>🎉 Secret found!</h2>
      <p>Nice work — the easter egg is active for this session.</p>
      <p><strong>Teacher note:</strong> you can now see the <code>found_easter_egg</code> flag in your session.</p>
      <p style="margin-top:12px;"><a href="/snake" style="display:inline-block;padding:8px 12px;background:#0b3d2e;color:#fff;border-radius:6px;text-decoration:none;">Play Snake</a></p>
      <p style="font-family:monospace;background:#fff;padding:6px;border-radius:4px;display:inline-block;margin-top:8px;">Keep smiling, CS Teacher!</p>
    </div>
    </body></html>
    """
    return render_template_string(secret_html)

@app.route("/snake")
def snake():
    # require easter-egg flag in session
    if not session.get("found_easter_egg"):
        return ("", 404)
    return render_template("snake.html")

# ---------- Checkout route (government) ----------
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    # require customer login
    if not session.get("customer_id"):
        flash("You must be logged in as a customer to checkout.", "warning")
        return redirect(url_for("login", next=url_for("checkout")))

    cart = session.get("cart", {}) or {}
    if not cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("products"))

    db = get_db()
    placeholders = ",".join("?" for _ in cart.keys())
    rows = db.execute(f"SELECT id, sku, name, price, stock FROM products WHERE sku IN ({placeholders})", tuple(cart.keys())).fetchall()
    prod_map = {r["sku"]: dict(r) for r in rows}
    items = []
    total = 0.0
    for sku, qty in cart.items():
        p = prod_map.get(sku)
        if not p:
            flash(f"Product {sku} not found, removed from cart.", "warning")
            continue
        subtotal = (p["price"] or 0.0) * int(qty)
        total += subtotal
        items.append({"id": p["id"], "sku": sku, "name": p["name"], "price": p["price"], "qty": int(qty), "stock": p["stock"], "subtotal": subtotal})

    if request.method == "GET":
        return render_template("checkout.html", items=items, total=total)

    # POST: collect gov fields and files
    agency = (request.form.get("agency") or "").strip()
    authorized_officer = (request.form.get("authorized_officer") or "").strip()
    official_email = (request.form.get("official_email") or "").strip()
    position_clearance = (request.form.get("position_clearance") or "").strip()
    contact_number = (request.form.get("contact_number") or "").strip()

    po_number = (request.form.get("po_number") or "").strip()
    contract_reference = (request.form.get("contract_reference") or "").strip()
    funding_source = (request.form.get("funding_source") or "").strip()

    vendor_id = (request.form.get("vendor_id") or "").strip()
    export_license_status = (request.form.get("export_license_status") or "").strip()
    delivery_location = (request.form.get("delivery_location") or "").strip()
    required_delivery_date = (request.form.get("required_delivery_date") or "").strip()
    payment_method = (request.form.get("payment_method") or "").strip()

    declaration = request.form.get("declaration") == "on"

    if not official_email:
        flash("Official email is required.", "danger")
        return redirect(url_for("checkout"))
    if not declaration:
        flash("You must confirm you are an authorized government representative.", "danger")
        return redirect(url_for("checkout"))
    if not is_official_email(official_email):
        flash("Official government email required (e.g. name@domain.gov).", "danger")
        return redirect(url_for("checkout"))

    # file validation + save helper
    ALLOWED_DOC_EXT = {".pdf", ".png", ".jpg", ".jpeg"}
    MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

    def _save_file_private_valid(field_name):
        f = request.files.get(field_name)
        if f and f.filename:
            filename = secure_filename(f.filename)
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_DOC_EXT:
                raise ValueError(f"Invalid file type for {field_name}.")
            f.stream.seek(0, os.SEEK_END)
            size = f.stream.tell()
            f.stream.seek(0)
            if size > MAX_UPLOAD_BYTES:
                raise ValueError(f"File too large for {field_name}.")
            dest_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
            dest = PRIVATE_UPLOADS / dest_name
            f.save(str(dest))
            return dest.name
        return None

    try:
        auth_doc_name = _save_file_private_valid("auth_doc")
        digital_sig_name = _save_file_private_valid("digital_signature")
    except ValueError as ve:
        flash(str(ve), "danger")
        return redirect(url_for("checkout"))

    if not auth_doc_name:
        flash("Authorization document is required.", "danger")
        return redirect(url_for("checkout"))

    auth_doc_path = auth_doc_name
    end_user_cert_path = None
    digital_sig_path = digital_sig_name


    # --- in your checkout POST handler, after you collect form fields ---
    # prevent saving orders without encryption key (avoids NULLs)
    if fernet is None:
        flash("Server encryption key (DATA_ENC_KEY) not configured — cannot place order. Contact admin.", "danger")
        return redirect(url_for("checkout"))

    # encrypt the sensitive fields (official_email left plaintext so emails still work)
    agency_enc = encrypt_field(agency)
    authorized_officer_enc = encrypt_field(authorized_officer)
    position_clearance_enc = encrypt_field(position_clearance)
    contact_number_enc = encrypt_field(contact_number)
    po_number_enc = encrypt_field(po_number)
    contract_reference_enc = encrypt_field(contract_reference)
    funding_source_enc = encrypt_field(funding_source)
    delivery_location_enc = encrypt_field(delivery_location)
    payment_method_enc = encrypt_field(payment_method)

    try:
        db.execute("BEGIN")
        # Re-check stock availability inside transaction
        for it in items:
            cur = db.execute("SELECT stock FROM products WHERE id = ?", (it["id"],)).fetchone()
            if not cur or (cur["stock"] or 0) < it["qty"]:
                raise ValueError(f"Insufficient stock for {it['name']}")

        # find or create customer by official_email
        cur = db.execute("SELECT id FROM customers WHERE email = ?", (official_email,)).fetchone()
        if cur:
            customer_id = cur["id"]
            db.execute("UPDATE customers SET name = ? WHERE id = ?", (authorized_officer, customer_id))
        else:
            created_at = datetime.utcnow().isoformat()
            cur = db.execute("INSERT INTO customers (name, email, created_at) VALUES (?, ?, ?)", (authorized_officer, official_email, created_at))
            customer_id = cur.lastrowid

        # prepare order insert with government fields
        created_at = datetime.utcnow().isoformat()

        order_cols = ["customer_id", "total", "status", "created_at",
                      "agency", "authorized_officer", "official_email", "position_clearance", "contact_number",
                      "po_number", "contract_reference", "funding_source",
                      "auth_doc", "vendor_id", "end_user_cert", "export_license_status",
                      "delivery_location", "required_delivery_date", "payment_method",
                      "declaration_agreed", "digital_signature"]
        order_vals = [customer_id, total, "placed", created_at,
                      agency_enc, authorized_officer_enc, official_email, position_clearance_enc, contact_number_enc,
                      po_number_enc, contract_reference_enc, funding_source_enc,
                      auth_doc_path, vendor_id, end_user_cert_path, export_license_status,
                      delivery_location_enc, required_delivery_date, payment_method_enc,
                      int(declaration), digital_sig_path]

        placeholders = ",".join("?" for _ in order_cols)
        sql = f"INSERT INTO orders ({','.join(order_cols)}) VALUES ({placeholders})"
        cur = db.execute(sql, tuple(order_vals))
        order_id = cur.lastrowid

        # insert items and decrement stock
        for it in items:
            db.execute("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                       (order_id, it["id"], it["qty"], it["price"]))
            db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (it["qty"], it["id"]))

        db.commit()
        # clear session cart and persisted cart
        session.pop("cart", None)
        if session.get("customer_id"):
            save_customer_cart(session["customer_id"], {})

        # send confirmation email (try official_email first, then logged-in customer email)
        recipient = official_email or None
        recipient_name = authorized_officer or session.get("customer_name")
        if not recipient and session.get("customer_id"):
            cur = db.execute("SELECT email, name FROM customers WHERE id = ?", (session["customer_id"],)).fetchone()
            if cur:
                recipient = cur["email"]
                recipient_name = cur["name"]

        if recipient:
            try:
                send_order_confirmation_email(recipient, recipient_name, order_id, items, total)
            except Exception:
                # swallow email exceptions so checkout flow is not blocked
                current_app.logger.exception("Unexpected error sending confirmation email")

        flash("Order placed. Thank you!", "success")
        return redirect(url_for("order_success", order_id=order_id))
    except Exception as e:
        db.rollback()
        flash(str(e), "danger")
        return redirect(url_for("cart_view"))

# -- Order success page -----------------------------------------
@app.route("/order/success/<int:order_id>")
def order_success(order_id):
    db = get_db()
    order = db.execute("SELECT o.id, o.total, o.status, o.created_at, c.name, c.email FROM orders o LEFT JOIN customers c ON o.customer_id = c.id WHERE o.id = ?", (order_id,)).fetchone()
    items = db.execute("SELECT oi.quantity, oi.unit_price, p.name FROM order_items oi JOIN products p ON oi.product_id = p.id WHERE oi.order_id = ?", (order_id,)).fetchall()
    return render_template("order_success.html", order=order, items=items)

@app.route("/product/<sku>")
def product_detail(sku):
    db = get_db()
    sku_upper = sku.upper()
    p = db.execute("SELECT id, sku, name, description, price, image, stock FROM products WHERE sku = ?", (sku_upper,)).fetchone()
    if not p:
        return redirect(url_for("products"))
    return render_template("product_detail.html", product=dict(p))

# inject cart count into all templates
@app.context_processor
def inject_cart_count():
    cart = session.get("cart", {}) if session is not None else {}
    try:
        count = sum(int(v) for v in cart.values()) if cart else 0
    except Exception:
        count = 0
    return {"cart_count": count}

# Save uploads to a private folder (not served by static)
PRIVATE_UPLOADS = Path(__file__).parent / "private_uploads"
PRIVATE_UPLOADS.mkdir(parents=True, exist_ok=True)

def _save_file_private(field_name):
    f = request.files.get(field_name)
    if f and f.filename:
        filename = secure_filename(f.filename)
        dest = PRIVATE_UPLOADS / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
        f.save(str(dest))
        return dest.name
    return None

# Example simple domain whitelist check (server-side)
ALLOWED_GOV_DOMAINS = (".gov", ".gov.au", ".mil")
def is_official_email(email: str) -> bool:
    email = (email or "").strip().lower()
    return any(email.endswith(d) for d in ALLOWED_GOV_DOMAINS)

# In your checkout POST processing (replace save to static with _save_file_private and validate):
# auth_doc_name = _save_file_private("auth_doc")
# end_user_name = _save_file_private("end_user_cert")
# ...
# if not is_official_email(official_email):
#     flash("Official government email required (e.g. name@domain.gov).", "danger")
#     return redirect(url_for("checkout"))

# Admin-only download route for private files
@app.route("/admin/uploads/<filename>")
@login_required
def admin_download_upload(filename):
    try:
        return send_from_directory(str(PRIVATE_UPLOADS), filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)

# --- Admin: orders list and order detail (review / edit export license) ---
@app.route("/admin/orders")
@login_required
def admin_orders():
    """List orders. filter=query param: 'current' (default) or 'previous'"""
    db = get_db()
    filt = request.args.get("filter", "current")
    if filt == "previous":
        rows = db.execute(
            "SELECT o.*, c.name AS customer_name FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE o.status IN ('completed','shipped','cancelled') ORDER BY o.created_at DESC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT o.*, c.name AS customer_name FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE o.status NOT IN ('completed','shipped','cancelled') ORDER BY o.created_at DESC"
        ).fetchall()
    return render_template("admin_orders.html", orders=rows, filter=filt)

@app.route("/admin/order/<int:order_id>", methods=["GET", "POST"])
@login_required
def admin_order_detail(order_id):
    db = get_db()

    # Handle updates from the admin form
    if request.method == "POST":
        status = (request.form.get("status") or "").strip()
        export_status = (request.form.get("export_status") or "").strip()

        # basic validation of allowed values
        allowed_status = {"placed", "processing", "shipped", "cancelled"}
        allowed_export = {"approved", "exempt", "processing", "pending"}

        if status not in allowed_status:
            flash("Invalid order status.", "danger")
            return redirect(url_for("admin_order_detail", order_id=order_id))
        if export_status not in allowed_export:
            flash("Invalid export status.", "danger")
            return redirect(url_for("admin_order_detail", order_id=order_id))

        db.execute(
            "UPDATE orders SET status = ?, export_license_status = ? WHERE id = ?",
            (status, export_status, order_id),
        )
        db.commit()
        flash("Order updated.", "success")
        return redirect(url_for("admin_order_detail", order_id=order_id))

    order = db.execute(
        "SELECT o.*, c.name AS customer_name, c.email AS customer_email FROM orders o LEFT JOIN customers c ON o.customer_id = c.id WHERE o.id = ?",
        (order_id,),
    ).fetchone()
    items = db.execute(
        "SELECT oi.quantity, oi.unit_price, p.name FROM order_items oi JOIN products p ON oi.product_id = p.id WHERE oi.order_id = ?",
        (order_id,),
    ).fetchall()

    # decrypt sensitive fields for admin display (if DATA_ENC_KEY provided)
    if order:
        order = dict(order)
        _to_decrypt = [
            "agency",
            "authorized_officer",
            "position_clearance",
            "contact_number",
            "po_number",
            "contract_reference",
            "funding_source",
            "delivery_location",
            "payment_method",
        ]
        for f in _to_decrypt:
            token = order.get(f)
            order[f + "_encrypted"] = token
            try:
                order[f + "_decrypted"] = decrypt_field(token) if token else None
            except Exception as e:
                current_app.logger.exception(
                    "Failed to decrypt order %s field %s: %s", order.get("id"), f, e
                )
                order[f + "_decrypted"] = None

    return render_template("admin_order_detail.html", order=order, items=items)

@app.route("/cart/remove", methods=["POST"])
def cart_remove():
    """Remove an SKU from the session cart (template calls url_for('cart_remove'))."""
    sku = (request.form.get("sku") or "").strip().upper()
    if not sku:
        return redirect(request.referrer or url_for("cart_view"))

    cart = _cart_get()
    if sku in cart:
        cart.pop(sku, None)
        _cart_set(cart)
        # persist change if customer is logged in
        try:
            save_cart_if_logged_in()
        except Exception:
            # silent fail-safe if persistence helpers removed/absent
            pass
        flash("Removed from cart.", "success")
    return redirect(request.referrer or url_for("cart_view"))

@app.route("/sw.js")
def service_worker():
    # serve the static service worker file at site root so its scope is '/'
    return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")

def send_order_confirmation_email(to_email, recipient_name, order_id, items, total):
    """Send a simple order confirmation email via SMTP. Returns True on success."""
    SMTP_HOST = os.environ.get("SMTP_HOST")
    if not SMTP_HOST:
        # SMTP not configured
        current_app.logger.debug("SMTP_HOST not set, skipping email.")
        return False

    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASS = os.environ.get("SMTP_PASS")
    FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER or "no-reply@example.com")

    msg = EmailMessage()
    msg["Subject"] = f"Order #{order_id} placed"
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    # Plain text body
    lines = [f"Hello {recipient_name or ''},", "", f"Your order #{order_id} has been placed.", "", "Order details:"]
    for it in (items or []):
        lines.append(f"- {it.get('qty',0)} x {it.get('name','')} — ${float(it.get('subtotal',0)):.2f}")
    lines.append("")
    lines.append(f"Total: ${float(total):.2f}")
    lines.append("")
    lines.append("Thank you for your order.")
    plain = "\n".join(lines)

    # Simple HTML body
    html_items = "".join(f"<li>{it.get('qty',0)} × {it.get('name','')} — ${float(it.get('subtotal',0)):.2f}</li>" for it in (items or []))
    html = f"""
    <html>
      <body>
        <p>Hello {recipient_name or ''},</p>
        <p>Your order <strong>#{order_id}</strong> has been placed.</p>
        <p>Order details:</p>
        <ul>{html_items}</ul>
        <p><strong>Total: ${float(total):.2f}</strong></p>
        <p>Thank you for your order.</p>
      </body>
    </html>
    """

    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls(context=context)
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        current_app.logger.debug("Order confirmation email sent to %s", to_email)
        return True
    except Exception as e:
        current_app.logger.exception("Failed to send order confirmation email: %s", e)
        return False

@app.route("/admin/debug")
@login_required
def admin_debug():
    """
    Simple debug endpoint to verify the DATA_ENC_KEY / Fernet availability.
    Returns JSON:
      - DATA_ENC_KEY_set: whether the env var exists
      - fernet_init: whether Fernet() could be instantiated (boolean)
      - fernet_test_decrypt_ok: whether a local encrypt/decrypt round-trip succeeded
      - error: optional error message if Fernet init failed
    """
    key = os.environ.get("DATA_ENC_KEY")
    result = {"DATA_ENC_KEY_set": bool(key)}
    if not key:
        return jsonify(result)

    try:
        f = Fernet(key.encode())
        result["fernet_init"] = True
        # do a safe local round-trip to ensure the key works (does not touch DB)
        token = f.encrypt(b"__debug__").decode()
        ok = (f.decrypt(token.encode()).decode() == "__debug__")
        result["fernet_test_decrypt_ok"] = bool(ok)
    except Exception as e:
        result["fernet_init"] = False
        result["error"] = str(e)

    return jsonify(result)

# session timeout in minutes (default 10)
SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "10"))
# absolute max session age (minutes). After this age session is invalidated regardless of activity.
SESSION_MAX_AGE_MINUTES = int(os.environ.get("SESSION_MAX_AGE_MINUTES", "1440"))  # 24 hours default

@app.before_request
def enforce_session_timeout():
    """
    Invalidate session if inactive longer than SESSION_TIMEOUT_MINUTES.
    Keeps session non-permanent (do not rely on browser to drop cookies).
    """
    # skip session checks for static assets, service worker and simple health/debug endpoints
    if request.path.startswith(("/static", "/sw.js", "/favicon.ico", "/admin/debug", "/admin/uploads")):
        return

    # update or expire session last_active timestamp
    now_ts = datetime.now(timezone.utc).timestamp()
    last = session.get("last_active")
    timeout_secs = SESSION_TIMEOUT_MINUTES * 60

    # absolute session age check (created_at)
    created = session.get("created_at")
    if created:
        try:
            created_ts = float(created)
        except Exception:
            created_ts = None
        if created_ts:
            max_age_secs = SESSION_MAX_AGE_MINUTES * 60
            if (now_ts - created_ts) > max_age_secs:
                session.clear()
                if request.path.startswith("/admin"):
                    flash("Session expired. Please log in again.", "info")
                    return redirect(url_for("admin_login", next=request.path))
                return

    if last:
        try:
            last_ts = float(last)
        except Exception:
            last_ts = None

        if last_ts and (now_ts - last_ts) > timeout_secs:
            # expire session
            session.clear()
            # If an admin page was being accessed, redirect to admin login
            if request.path.startswith("/admin"):
                flash("Session expired due to inactivity. Please log in again.", "info")
                return redirect(url_for("admin_login", next=request.path))
            # otherwise allow request to continue as anonymous (session cleared)

    # refresh last_active for logged-in users (only for non-static interactive requests)
    if session.get("customer_id") or session.get("is_admin"):
        session["last_active"] = now_ts
        # set created_at when session first established (keeps absolute age tracking)
        if "created_at" not in session:
            session["created_at"] = now_ts

@app.route("/debug/session")
def debug_session():
    # dev-only: allow when app.debug or request from localhost
    if not app.debug and request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)
    # convert session values to strings for JSON safety
    return jsonify({k: str(v) for k, v in session.items()}), 200

if __name__ == "__main__":
    # ensure DB schema has the required order columns before serving
    _ensure_schema_startup()
    app.run(debug=True)