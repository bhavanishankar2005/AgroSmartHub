import os
import uuid
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from werkzeug.security import generate_password_hash, check_password_hash

import pymysql
import pymysql.cursors

# --- DB configuration ---
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASS = os.environ.get('DB_PASS', 'root')
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_NAME = os.environ.get('DB_NAME', 'agrosmarthub')
DB_PORT = int(os.environ.get('DB_PORT', 3306))

# --- Image Upload Configuration ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
CORS(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    """Return a pymysql connection (MySQL only)."""
    conn = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        port=DB_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        charset='utf8mb4'
    )
    return conn

def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                phonenumber VARCHAR(15),
                role VARCHAR(20),
                reset_token VARCHAR(128),
                reset_expiry DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token VARCHAR(128) PRIMARY KEY,
                user_id INT,
                expiry DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS products (
                product_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                productname VARCHAR(100) NOT NULL,
                productdescription TEXT,
                price DECIMAL(10,2) NOT NULL,
                quantity INT NOT NULL,
                image_filename VARCHAR(255),
                seller_phone VARCHAR(32),
                approval_status VARCHAR(20) DEFAULT 'pending',
                approval_comment VARCHAR(500),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            
            # Add approval and seller_phone columns if they don't exist
            with conn.cursor() as alt_cur:
                try:
                    alt_cur.execute("ALTER TABLE products ADD COLUMN approval_status VARCHAR(20) DEFAULT 'pending'")
                except:
                    pass
                try:
                    alt_cur.execute("ALTER TABLE products ADD COLUMN approval_comment VARCHAR(500)")
                except:
                    pass
                try:
                    alt_cur.execute("ALTER TABLE products ADD COLUMN seller_phone VARCHAR(32)")
                except:
                    pass
            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS carts (
                cart_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS cart_items (
                item_id INT AUTO_INCREMENT PRIMARY KEY,
                cart_id INT NOT NULL,
                product_id INT,
                productname VARCHAR(255) NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                quantity INT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (cart_id) REFERENCES carts(cart_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                delivery_address TEXT,
                contact_phone VARCHAR(32),
                total DECIMAL(12,2) DEFAULT 0.00,
                status VARCHAR(30) DEFAULT 'placed',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS order_items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                product_id INT,
                productname VARCHAR(255) NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                quantity INT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
        conn.commit()
        
        # Insert test user if not exists
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = 'testuser'")
            if not cur.fetchone():
                hashed_pass = generate_password_hash('test123')
                cur.execute(
                    "INSERT INTO users (username, password, role, phonenumber) VALUES (%s, %s, %s, %s)",
                    ('testuser', hashed_pass, 'buyer', '9876543210')
                )
                conn.commit()
    except Exception as e:
        print(f"Database init error: {e}")
    finally:
        conn.close()

@app.route('/test', methods=['GET'])
def test_connection():
    """Test API connectivity"""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM users")
            result = cur.fetchone()
        conn.close()
        return jsonify({'success': True, 'message': 'API is working', 'users': result['count']}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/orders/<int:oid>', methods=['GET'])
def get_order(oid):
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT order_id, user_id, delivery_address, contact_phone, total, status, created_at FROM orders WHERE order_id = %s", (oid,))
            order = cur.fetchone()
            if not order:
                return jsonify({'error': 'order not found'}), 404
            if order['user_id'] != user_id:
                return jsonify({'error': 'forbidden'}), 403

            cur.execute("SELECT id, product_id, productname, price, quantity FROM order_items WHERE order_id = %s", (oid,))
            items = cur.fetchall()
        return jsonify({'order': order, 'items': items}), 200
    finally:
        conn.close()


@app.route('/orders', methods=['GET'])
def list_orders():
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT order_id, total, status, created_at FROM orders WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            rows = cur.fetchall()
        return jsonify(rows), 200
    finally:
        conn.close()

# --- AUTHENTICATION ENDPOINTS ---

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    phonenumber = data.get('phonenumber')
    role = data.get('role', 'user')

    if isinstance(role, dict):
        vals = [v for v in role.values() if isinstance(v, str)]
        role = vals[0] if vals else 'user'
    else:
        role = str(role)

    if not username or not password:
        return jsonify({'error': 'username and password required'}), 400

    hashed = generate_password_hash(password)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password, phonenumber, role) VALUES (%s, %s, %s, %s)",
                (username, hashed, phonenumber, role)
            )
        conn.commit()
    except pymysql.err.IntegrityError:
        conn.rollback()
        return jsonify({'error': 'username already exists'}), 409
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'user registered'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'username and password required'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password, role FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
        if not row or not check_password_hash(row['password'], password):
            return jsonify({'error': 'invalid credentials'}), 401

        token = str(uuid.uuid4())
        expiry_dt = datetime.utcnow() + timedelta(hours=12)
        expiry_str = expiry_dt.strftime('%Y-%m-%d %H:%M:%S')
        with conn.cursor() as cur:
            cur.execute("INSERT INTO auth_tokens (token, user_id, expiry) VALUES (%s, %s, %s)",
                        (token, row['id'], expiry_str))
        conn.commit()
        return jsonify({'success': True, 'message': 'login successful', 'token': token, 'role': row['role']}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

def auth_required(req):
    """Extract user_id from Bearer token"""
    auth = req.headers.get('Authorization', '')
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    token = parts[1]
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, expiry FROM auth_tokens WHERE token = %s", (token,))
            row = cur.fetchone()
        if not row:
            return None
        expiry = row['expiry']
        if isinstance(expiry, datetime):
            exp_dt = expiry
        else:
            exp_dt = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S')
        if exp_dt < datetime.utcnow():
            return None
        return row['user_id']
    finally:
        conn.close()

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json() or {}
    username = data.get('username')
    if not username:
        return jsonify({'error': 'username required'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'user not found'}), 404

            token = str(uuid.uuid4())
            expiry = (datetime.utcnow() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
            cur.execute("UPDATE users SET reset_token = %s, reset_expiry = %s WHERE username = %s",
                        (token, expiry, username))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'reset token generated', 'reset_token': token}), 200

@app.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json() or {}
    username = data.get('username')
    token = data.get('token')
    new_password = data.get('new_password')
    if not username or not token or not new_password:
        return jsonify({'error': 'username, token and new_password required'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT reset_token, reset_expiry FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if not row or row['reset_token'] != token:
                return jsonify({'error': 'invalid token'}), 400
            expiry = row['reset_expiry']
            if expiry is None:
                return jsonify({'error': 'invalid token'}), 400
            if isinstance(expiry, datetime):
                exp_dt = expiry
            else:
                exp_dt = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S')
            if exp_dt < datetime.utcnow():
                return jsonify({'error': 'token expired'}), 400

            hashed = generate_password_hash(new_password)
            cur.execute("UPDATE users SET password = %s, reset_token = NULL, reset_expiry = NULL, updated_at = CURRENT_TIMESTAMP WHERE username = %s",
                        (hashed, username))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'password updated'}), 200

# --- PRODUCT CRUD ENDPOINTS ---

@app.route('/products', methods=['GET'])
def list_products():
    """Get all products (visible to all users - only approved products)"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT product_id, productname, productdescription, price, quantity, image_filename, seller_phone FROM products WHERE approval_status = 'approved' ORDER BY created_at DESC")
            rows = cur.fetchall()
        return jsonify(rows)
    finally:
        conn.close()

@app.route('/my-products', methods=['GET'])
def my_products():
    """Get products belonging to the authenticated farmer"""
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT product_id, productname, productdescription, price, quantity, image_filename, seller_phone, approval_status, approval_comment FROM products WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            rows = cur.fetchall()
        return jsonify(rows)
    finally:
        conn.close()

@app.route('/products/<int:pid>', methods=['GET'])
def get_product(pid):
    """Get single product by ID"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT product_id, productname, productdescription, price, quantity, image_filename, seller_phone FROM products WHERE product_id = %s", (pid,))
            row = cur.fetchone()
        if not row:
            return jsonify({'error': 'not found'}), 404
        return jsonify(row)
    finally:
        conn.close()

@app.route('/products', methods=['POST'])
def create_product():
    """Create new product with image upload"""
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    productname = request.form.get('productname')
    productdescription = request.form.get('productdescription', '')
    price = request.form.get('price')
    quantity = request.form.get('quantity')
    seller_phone = request.form.get('seller_phone')
    image_file = request.files.get('image')

    if not productname or price is None or quantity is None:
        return jsonify({'error': 'productname, price, quantity required'}), 400

    image_filename = None
    if image_file and image_file.filename != '':
        if not allowed_file(image_file.filename):
            return jsonify({'error': 'invalid file type. Allowed: png, jpg, jpeg, gif, webp'}), 400
        
        # Generate unique filename
        ext = image_file.filename.rsplit('.', 1)[1].lower()
        image_filename = f"{uuid.uuid4()}.{ext}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
        image_file.save(image_path)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO products (user_id, productname, productdescription, price, quantity, image_filename, seller_phone, approval_status)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (user_id, productname, productdescription, float(price), int(quantity), image_filename, seller_phone, 'pending'))
            pid = cur.lastrowid
        conn.commit()
        return jsonify({'message': 'created', 'product_id': pid, 'image_filename': image_filename, 'approval_status': 'pending'}), 201
    except Exception as e:
        if image_filename:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/products/<int:pid>', methods=['PUT'])
def update_product(pid):
    """Update product with optional image upload"""
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    productname = request.form.get('productname')
    productdescription = request.form.get('productdescription')
    price = request.form.get('price')
    quantity = request.form.get('quantity')
    seller_phone = request.form.get('seller_phone')
    image_file = request.files.get('image')

    fields = []
    vals = []

    if productname:
        fields.append("productname = %s")
        vals.append(productname)
    if productdescription:
        fields.append("productdescription = %s")
        vals.append(productdescription)
    if seller_phone is not None:
        fields.append("seller_phone = %s")
        vals.append(seller_phone)
    if price is not None:
        fields.append("price = %s")
        vals.append(float(price))
    if quantity is not None:
        fields.append("quantity = %s")
        vals.append(int(quantity))

    # Handle image update
    old_image = None
    if image_file and image_file.filename != '':
        if not allowed_file(image_file.filename):
            return jsonify({'error': 'invalid file type'}), 400
        
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT image_filename FROM products WHERE product_id = %s AND user_id = %s", (pid, user_id))
                row = cur.fetchone()
                if not row:
                    return jsonify({'error': 'product not found or not owned by user'}), 404
                old_image = row['image_filename']
        finally:
            conn.close()

        # Save new image
        ext = image_file.filename.rsplit('.', 1)[1].lower()
        image_filename = f"{uuid.uuid4()}.{ext}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
        image_file.save(image_path)
        
        fields.append("image_filename = %s")
        vals.append(image_filename)

    if not fields:
        return jsonify({'error': 'no fields to update'}), 400

    # Reset approval status when product is edited
    fields.append("approval_status = %s")
    vals.append('pending')
    fields.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(pid)

    query = f"UPDATE products SET {', '.join(fields)} WHERE product_id = %s AND user_id = %s"
    vals.append(user_id)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(query, vals)
        conn.commit()
        
        # Delete old image if new one was uploaded
        if old_image and image_file:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_image)
            if os.path.exists(old_path):
                os.remove(old_path)
        
        return jsonify({'message': 'updated', 'approval_status': 'pending'}), 200
    finally:
        conn.close()

@app.route('/products/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    """Delete product and its image"""
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT image_filename FROM products WHERE product_id = %s", (pid,))
            row = cur.fetchone()
            if row and row['image_filename']:
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], row['image_filename'])
                if os.path.exists(image_path):
                    os.remove(image_path)
            
            cur.execute("DELETE FROM products WHERE product_id = %s AND user_id = %s", (pid, user_id))
        conn.commit()
        return jsonify({'message': 'deleted'}), 200
    finally:
        conn.close()


# --- CART ENDPOINTS ---

def _get_or_create_cart_id(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT cart_id FROM carts WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            return row['cart_id']
        cur.execute("INSERT INTO carts (user_id) VALUES (%s)", (user_id,))
        return cur.lastrowid


@app.route('/cart', methods=['GET'])
def get_cart():
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    conn = get_db()
    try:
        cart_id = None
        with conn.cursor() as cur:
            cur.execute("SELECT cart_id FROM carts WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return jsonify([]), 200
            cart_id = row['cart_id']

            cur.execute("SELECT item_id, product_id, productname, price, quantity FROM cart_items WHERE cart_id = %s", (cart_id,))
            items = cur.fetchall()
        return jsonify(items), 200
    finally:
        conn.close()


@app.route('/cart', methods=['POST'])
def add_cart_item():
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    product_id = data.get('product_id')
    productname = data.get('productname')
    price = data.get('price')
    quantity = int(data.get('quantity', 1))

    if not productname or price is None:
        return jsonify({'error': 'productname and price required'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cart_id = _get_or_create_cart_id(conn, user_id)

            # If same product already in cart, increase quantity
            cur.execute("SELECT item_id, quantity FROM cart_items WHERE cart_id = %s AND productname = %s", (cart_id, productname))
            existing = cur.fetchone()
            if existing:
                new_q = existing['quantity'] + quantity
                cur.execute("UPDATE cart_items SET quantity = %s, updated_at = CURRENT_TIMESTAMP WHERE item_id = %s", (new_q, existing['item_id']))
                conn.commit()
                return jsonify({'message': 'updated', 'item_id': existing['item_id']}), 200

            cur.execute("INSERT INTO cart_items (cart_id, product_id, productname, price, quantity) VALUES (%s, %s, %s, %s, %s)",
                        (cart_id, product_id, productname, float(price), int(quantity)))
            item_id = cur.lastrowid
        conn.commit()
        return jsonify({'message': 'added', 'item_id': item_id}), 201
    finally:
        conn.close()


@app.route('/cart/item/<int:item_id>', methods=['PUT'])
def update_cart_item(item_id):
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    quantity = data.get('quantity')
    if quantity is None:
        return jsonify({'error': 'quantity required'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ci.item_id FROM cart_items ci JOIN carts c ON ci.cart_id = c.cart_id WHERE ci.item_id = %s AND c.user_id = %s", (item_id, user_id))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'item not found'}), 404
            cur.execute("UPDATE cart_items SET quantity = %s, updated_at = CURRENT_TIMESTAMP WHERE item_id = %s", (int(quantity), item_id))
        conn.commit()
        return jsonify({'message': 'updated'}), 200
    finally:
        conn.close()


@app.route('/cart/item/<int:item_id>', methods=['DELETE'])
def delete_cart_item(item_id):
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ci.item_id FROM cart_items ci JOIN carts c ON ci.cart_id = c.cart_id WHERE ci.item_id = %s AND c.user_id = %s", (item_id, user_id))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'item not found'}), 404
            cur.execute("DELETE FROM cart_items WHERE item_id = %s", (item_id,))
        conn.commit()
        return jsonify({'message': 'deleted'}), 200
    finally:
        conn.close()


@app.route('/cart/checkout', methods=['POST'])
def checkout_cart():
    user_id = auth_required(request)
    if not user_id:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    delivery_address = (data.get('delivery_address') or '').strip()
    contact_phone = (data.get('contact_phone') or '').strip()

    # server-side validation
    if not delivery_address or len(delivery_address) < 10:
        return jsonify({'error': 'delivery_address required (min 10 chars)'}), 400

    # normalize phone: digits only
    digits = ''.join(c for c in contact_phone if c.isdigit())
    if contact_phone and (len(digits) < 7 or len(digits) > 15):
        return jsonify({'error': 'contact_phone invalid'}), 400
    contact_phone = digits

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cart_id FROM carts WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'cart empty'}), 400
            cart_id = row['cart_id']

            # Fetch items
            cur.execute("SELECT item_id, product_id, productname, price, quantity FROM cart_items WHERE cart_id = %s", (cart_id,))
            items = cur.fetchall()
            if not items:
                return jsonify({'error': 'cart empty'}), 400

            # Validate stock and compute total
            total = 0.0
            for it in items:
                qty = int(it['quantity'])
                price = float(it['price'])
                if it['product_id']:
                    cur.execute("SELECT quantity FROM products WHERE product_id = %s", (it['product_id'],))
                    prod = cur.fetchone()
                    if not prod or prod['quantity'] < qty:
                        conn.rollback()
                        return jsonify({'error': f"Insufficient stock for {it['productname']}"}), 400
                total += price * qty

            # Create order
            cur.execute("INSERT INTO orders (user_id, delivery_address, contact_phone, total, status) VALUES (%s, %s, %s, %s, %s)",
                        (user_id, delivery_address, contact_phone, round(total,2), 'placed'))
            order_id = cur.lastrowid

            # Insert order items and deduct stock
            for it in items:
                cur.execute("INSERT INTO order_items (order_id, product_id, productname, price, quantity) VALUES (%s, %s, %s, %s, %s)",
                            (order_id, it['product_id'], it['productname'], float(it['price']), int(it['quantity'])))
                if it['product_id']:
                    cur.execute("UPDATE products SET quantity = quantity - %s WHERE product_id = %s", (int(it['quantity']), it['product_id']))

            # Clear cart items
            cur.execute("DELETE FROM cart_items WHERE cart_id = %s", (cart_id,))

        conn.commit()
        return jsonify({'message': 'checkout successful', 'order_id': order_id}), 200
    finally:
        conn.close()

# --- IMAGE SERVING ---

@app.route('/uploads/<filename>', methods=['GET'])
def serve_image(filename):
    """Serve uploaded images"""
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except Exception as e:
        return jsonify({'error': 'file not found'}), 404

# --- ADMIN ENDPOINTS ---

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')  # Change this to your secure password

def is_admin_token(token, conn):
    """Check if a token belongs to an admin user"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.role FROM auth_tokens t
                JOIN users u ON t.user_id = u.id
                WHERE t.token = %s AND u.role = 'admin'
            """, (token,))
            result = cur.fetchone()
            return result is not None
    except:
        return False

@app.route('/admin/test-password', methods=['POST'])
def test_admin_password():
    """Test admin password (for debugging)"""
    data = request.get_json() or {}
    password = data.get('password')
    
    return jsonify({
        'password_received': password,
        'admin_password_set': ADMIN_PASSWORD,
        'match': password == ADMIN_PASSWORD,
        'password_length': len(password) if password else 0,
        'admin_password_length': len(ADMIN_PASSWORD)
    }), 200

@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Admin login with single password"""
    data = request.get_json() or {}
    password = data.get('password')
    
    if not password:
        return jsonify({'error': 'password required'}), 400
    
    if password != ADMIN_PASSWORD:
        return jsonify({'error': 'invalid password'}), 401
    
    # Generate admin token
    token = str(uuid.uuid4())
    expiry_dt = datetime.utcnow() + timedelta(hours=24)
    expiry_str = expiry_dt.strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # First, ensure admin user exists (id = -1 doesn't work with FK, so use special approach)
            # Store admin token without foreign key reference - we'll handle it separately
            try:
                cur.execute(
                    "INSERT INTO auth_tokens (token, user_id, expiry) VALUES (%s, %s, %s)",
                    (token, -1, expiry_str)
                )
            except:
                # If FK fails, use a different approach - create a temporary admin entry
                cur.execute("SELECT id FROM users WHERE username = 'admin_user'")
                admin_user = cur.fetchone()
                
                if not admin_user:
                    # Create admin user if it doesn't exist
                    hashed_pass = generate_password_hash(ADMIN_PASSWORD)
                    cur.execute(
                        "INSERT INTO users (username, password, role, phonenumber) VALUES (%s, %s, %s, %s)",
                        ('admin_user', hashed_pass, 'admin', '0000000000')
                    )
                    admin_id = cur.lastrowid
                else:
                    admin_id = admin_user['id']
                
                cur.execute(
                    "INSERT INTO auth_tokens (token, user_id, expiry) VALUES (%s, %s, %s)",
                    (token, admin_id, expiry_str)
                )
        
        conn.commit()
        return jsonify({'success': True, 'message': 'admin login successful', 'token': token}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/admin/dashboard', methods=['GET'])
def admin_dashboard():
    """Get admin dashboard statistics"""
    token = request.headers.get('Authorization', '').split(' ')[-1]
    
    conn = get_db()
    try:
        if not is_admin_token(token, conn):
            return jsonify({'error': 'unauthorized'}), 401
        
        with conn.cursor() as cur:
            # Get statistics
            cur.execute("SELECT COUNT(*) as total FROM users")
            total_users = cur.fetchone()['total']
            
            cur.execute("SELECT COUNT(*) as total FROM users WHERE role = 'farmer'")
            total_farmers = cur.fetchone()['total']
            
            cur.execute("SELECT COUNT(*) as total FROM users WHERE role = 'buyer'")
            total_buyers = cur.fetchone()['total']
            
            cur.execute("SELECT COUNT(*) as total FROM products")
            total_products = cur.fetchone()['total']
            
            cur.execute("SELECT COUNT(*) as total FROM orders")
            total_orders = cur.fetchone()['total']
            
            cur.execute("SELECT COALESCE(SUM(total), 0) as total_sales FROM orders")
            total_sales = cur.fetchone()['total_sales']
            
            return jsonify({
                'success': True,
                'stats': {
                    'total_users': total_users,
                    'total_farmers': total_farmers,
                    'total_buyers': total_buyers,
                    'total_products': total_products,
                    'total_orders': total_orders,
                    'total_sales': float(total_sales)
                }
            }), 200
    finally:
        conn.close()

@app.route('/admin/users', methods=['GET'])
def admin_get_users():
    """Get all users for admin"""
    token = request.headers.get('Authorization', '').split(' ')[-1]
    
    conn = get_db()
    try:
        if not is_admin_token(token, conn):
            return jsonify({'error': 'unauthorized'}), 401
        
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, phonenumber, role, created_at FROM users ORDER BY created_at DESC")
            users = cur.fetchall()
            return jsonify({'success': True, 'users': users}), 200
    finally:
        conn.close()

@app.route('/admin/orders', methods=['GET'])
def admin_get_orders():
    """Get all orders for admin"""
    token = request.headers.get('Authorization', '').split(' ')[-1]
    
    conn = get_db()
    try:
        if not is_admin_token(token, conn):
            return jsonify({'error': 'unauthorized'}), 401
        
        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.order_id, o.user_id, u.username, o.total, o.status, o.created_at 
                FROM orders o 
                JOIN users u ON o.user_id = u.id 
                ORDER BY o.created_at DESC
            """)
            orders = cur.fetchall()
            return jsonify({'success': True, 'orders': orders}), 200
    finally:
        conn.close()

# --- PRODUCT APPROVAL ENDPOINTS ---

@app.route('/admin/products/pending', methods=['GET'])
def admin_get_pending_products():
    """Get all pending products for admin approval"""
    token = request.headers.get('Authorization', '').split(' ')[-1]
    
    conn = get_db()
    try:
        if not is_admin_token(token, conn):
            return jsonify({'error': 'unauthorized'}), 401
        
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.product_id, p.user_id, u.username, p.productname, p.productdescription, 
                       p.price, p.quantity, p.image_filename, p.approval_status, p.approval_comment, 
                       p.created_at, p.updated_at
                FROM products p 
                JOIN users u ON p.user_id = u.id 
                WHERE p.approval_status = 'pending'
                ORDER BY p.created_at ASC
            """)
            products = cur.fetchall()
            return jsonify({'success': True, 'products': products}), 200
    finally:
        conn.close()

@app.route('/admin/products/all', methods=['GET'])
def admin_get_all_products():
    """Get all products with approval status for admin"""
    token = request.headers.get('Authorization', '').split(' ')[-1]
    
    conn = get_db()
    try:
        if not is_admin_token(token, conn):
            return jsonify({'error': 'unauthorized'}), 401
        
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.product_id, p.user_id, u.username, p.productname, p.productdescription, 
                       p.price, p.quantity, p.image_filename, p.approval_status, p.approval_comment, 
                       p.created_at, p.updated_at
                FROM products p 
                JOIN users u ON p.user_id = u.id 
                ORDER BY p.created_at DESC
            """)
            products = cur.fetchall()
            return jsonify({'success': True, 'products': products}), 200
    finally:
        conn.close()

@app.route('/admin/products/<int:pid>/approve', methods=['POST'])
def admin_approve_product(pid):
    """Approve a product"""
    token = request.headers.get('Authorization', '').split(' ')[-1]
    data = request.get_json() or {}
    
    conn = get_db()
    try:
        if not is_admin_token(token, conn):
            return jsonify({'error': 'unauthorized'}), 401
        
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE products SET approval_status = %s, approval_comment = %s WHERE product_id = %s",
                ('approved', data.get('comment', ''), pid)
            )
        conn.commit()
        return jsonify({'success': True, 'message': 'Product approved'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/admin/products/<int:pid>/reject', methods=['POST'])
def admin_reject_product(pid):
    """Reject a product"""
    token = request.headers.get('Authorization', '').split(' ')[-1]
    data = request.get_json() or {}
    
    conn = get_db()
    try:
        if not is_admin_token(token, conn):
            return jsonify({'error': 'unauthorized'}), 401
        
        with conn.cursor() as cur:
            comment = data.get('comment', 'No reason provided')
            cur.execute(
                "UPDATE products SET approval_status = %s, approval_comment = %s WHERE product_id = %s",
                ('rejected', comment, pid)
            )
        conn.commit()
        return jsonify({'success': True, 'message': 'Product rejected'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)