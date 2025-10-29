from flask import Flask, render_template, g, request
import sqlite3
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import request, redirect, url_for, render_template

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "store.db"

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
    sql = "SELECT id, sku, name, description, price, image FROM products ORDER BY id"
    if limit:
        sql += " LIMIT ?"
        cur = db.execute(sql, (limit,))
    else:
        cur = db.execute(sql)
    rows = cur.fetchall()
    # convert to list of dicts for Jinja
    return [dict(r) for r in rows]

@app.route("/")
def index():
    featured = get_products(limit=3)
    return render_template("index.html", featured=featured)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/products")
def products():
    products = get_products()
    selected = request.args.get('selected')  # kept for client-side highlight logic if used
    return render_template("products.html", products=products, selected=selected)

@app.route("/admin/products", methods=["GET", "POST"])
def admin_products():
    db = get_db()
    if request.method == "POST":
        sku = request.form.get("sku")
        if not sku:
            return redirect(url_for("admin_products"))

        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price_raw = request.form.get("price", "").replace(",", "").strip()
        try:
            price_val = float(price_raw) if price_raw != "" else None
        except ValueError:
            price_val = None

        # handle image upload
        image_file = request.files.get("image")
        image_path = None
        if image_file and image_file.filename:
            images_dir = Path(__file__).parent / "static" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            filename = secure_filename(image_file.filename)
            dest = images_dir / filename
            image_file.save(str(dest))
            image_path = f"images/{filename}"

        # build update statement
        if price_val is None:
            # If price invalid, skip updating price
            if image_path:
                db.execute("UPDATE products SET name = ?, description = ?, image = ? WHERE sku = ?",
                           (name, description, image_path, sku))
            else:
                db.execute("UPDATE products SET name = ?, description = ? WHERE sku = ?",
                           (name, description, sku))
        else:
            if image_path:
                db.execute("UPDATE products SET name = ?, description = ?, price = ?, image = ? WHERE sku = ?",
                           (name, description, price_val, image_path, sku))
            else:
                db.execute("UPDATE products SET name = ?, description = ?, price = ? WHERE sku = ?",
                           (name, description, price_val, sku))

        db.commit()
        return redirect(url_for("admin_products"))

    # GET: load products from DB and render editor
    products = get_products()
    return render_template("edit_products.html", products=products)

if __name__ == "__main__":
    app.run(debug=True)