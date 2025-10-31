from flask import Flask, render_template, g, request, redirect, url_for, jsonify, session, flash
import sqlite3
from pathlib import Path
from datetime import datetime
import re
from werkzeug.utils import secure_filename
import os
from functools import wraps

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "store.db"
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-please-change")

def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(exc):
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

# simple login_required decorator
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
        ADMIN_PASS = os.environ.get("ADMIN_PASS", "password")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["is_admin"] = True
            next_url = request.args.get("next") or url_for("admin_products")
            return redirect(next_url)
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)