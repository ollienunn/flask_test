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

# simple login_required decorator
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped

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

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        ADMIN_USER = os.environ.get("ADMIN_USER", "Admin")
        ADMIN_PASS = os.environ.get("ADMIN_PASS", "MachZeroOwner")
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
    flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("products"))

# -- View / update cart -----------------------------------------
@app.route("/cart", methods=["GET"])
def cart_view():
    cart = _cart_get()
    items = []
    total = 0.0
    if cart:
        db = get_db()
        placeholders = ",".join("?" for _ in cart.keys())
        rows = db.execute(f"SELECT id, sku, name, price, image, stock FROM products WHERE sku IN ({placeholders})", tuple(cart.keys())).fetchall()
        prod_map = {r["sku"]: dict(r) for r in rows}
        for sku, qty in cart.items():
            p = prod_map.get(sku)
            if not p:
                continue
            subtotal = (p["price"] or 0.0) * qty
            total += subtotal
            items.append({"product": p, "qty": qty, "subtotal": subtotal})
    return render_template("cart.html", items=items, total=total)

@app.route("/cart/update", methods=["POST"])
def cart_update():
    # supports quantity updates and removal
    cart = _cart_get()
    action = request.form.get("action")
    sku = (request.form.get("sku") or "").strip().upper()
    if action == "remove":
        cart.pop(sku, None)
    elif action == "set":
        try:
            qty = int(request.form.get("qty") or 0)
        except ValueError:
            qty = 0
        if qty <= 0:
            cart.pop(sku, None)
        else:
            # clamp to available stock
            db = get_db()
            prod = db.execute("SELECT stock FROM products WHERE sku = ?", (sku,)).fetchone()
            if prod:
                if qty > (prod["stock"] or 0):
                    qty = prod["stock"]
                    flash(f"Quantity adjusted to available stock for {sku}.", "warning")
            cart[sku] = qty
    _cart_set(cart)
    return redirect(url_for("cart_view"))

# -- Checkout ----------------------------------------------------
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = _cart_get()
    if not cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("products"))

    db = get_db()
    # build items list from DB and calculate total
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
        subtotal = (p["price"] or 0.0) * qty
        total += subtotal
        items.append({"id": p["id"], "sku": sku, "name": p["name"], "price": p["price"], "qty": qty, "stock": p["stock"], "subtotal": subtotal})

    if request.method == "GET":
        return render_template("checkout.html", items=items, total=total)

    # POST: process payment stub + create order
    name = (request.form.get("name") or "Guest").strip()
    email = (request.form.get("email") or "").strip().lower()
    if not email:
        flash("Please provide an email for the order.", "danger")
        return redirect(url_for("checkout"))

    try:
        # begin transaction
        db.execute("BEGIN")
        # Re-check stock availability inside transaction
        for it in items:
            cur = db.execute("SELECT stock FROM products WHERE id = ?", (it["id"],)).fetchone()
            if not cur or (cur["stock"] or 0) < it["qty"]:
                raise ValueError(f"Insufficient stock for {it['name']}")

        # find or create customer
        cur = db.execute("SELECT id FROM customers WHERE email = ?", (email,)).fetchone()
        if cur:
            customer_id = cur["id"]
            db.execute("UPDATE customers SET name = ? WHERE id = ?", (name, customer_id))
        else:
            created_at = datetime.utcnow().isoformat()
            cur = db.execute("INSERT INTO customers (name, email, created_at) VALUES (?, ?, ?)", (name, email, created_at))
            customer_id = cur.lastrowid

        # insert order
        created_at = datetime.utcnow().isoformat()
        cur = db.execute("INSERT INTO orders (customer_id, total, status, created_at) VALUES (?, ?, ?, ?)",
                         (customer_id, total, "placed", created_at))
        order_id = cur.lastrowid

        # insert items and decrement stock
        for it in items:
            db.execute("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                       (order_id, it["id"], it["qty"], it["price"]))
            db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (it["qty"], it["id"]))

        db.commit()
        # clear cart
        session.pop("cart", None)
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