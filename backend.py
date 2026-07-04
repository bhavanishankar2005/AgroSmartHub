from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid

app = Flask(__name__)
CORS(app)

# Dummy data: stored in memory
products = [
    {
        "id": "1",
        "name": "Tomato",
        "price": 30,
        "quantity": 25,
        "description": "Fresh red tomatoes",
        "image": "https://via.placeholder.com/150"
    },
    {
        "id": "2",
        "name": "Potato",
        "price": 20,
        "quantity": 40,
        "description": "Organic potatoes",
        "image": "https://via.placeholder.com/150"
    }
]


# ---------------------------
# GET ALL PRODUCTS
# ---------------------------
@app.route("/products", methods=["GET"])
def get_products():
    return jsonify(products), 200


# ---------------------------
# ADD NEW PRODUCT
# ---------------------------
@app.route("/products", methods=["POST"])
def add_product():
    data = request.get_json()

    new_product = {
        "id": str(uuid.uuid4()),
        "name": data.get("name"),
        "price": data.get("price"),
        "quantity": data.get("quantity"),
        "description": data.get("description"),
        "image": data.get("image")
    }

    products.append(new_product)

    return jsonify({"message": "Product added", "product": new_product}), 201


# ---------------------------
# EDIT PRODUCT
# ---------------------------
@app.route("/products/<product_id>", methods=["PUT"])
def edit_product(product_id):
    data = request.get_json()

    for product in products:
        if product["id"] == product_id:
            product["name"] = data.get("name", product["name"])
            product["price"] = data.get("price", product["price"])
            product["quantity"] = data.get("quantity", product["quantity"])
            product["description"] = data.get("description", product["description"])
            product["image"] = data.get("image", product["image"])

            return jsonify({"message": "Product updated", "product": product}), 200

    return jsonify({"error": "Product not found"}), 404


# ---------------------------
# DELETE PRODUCT
# ---------------------------
@app.route("/products/<product_id>", methods=["DELETE"])
def delete_product(product_id):
    global products
    before = len(products)
    products = [p for p in products if p["id"] != product_id]

    if len(products) == before:
        return jsonify({"error": "Product not found"}), 404
    
    return jsonify({"message": "Product deleted"}), 200


# ---------------------------
# SEARCH PRODUCT (OPTIONAL)
# ---------------------------
@app.route("/products/search", methods=["GET"])
def search_product():
    query = request.args.get("q", "").lower()
    filtered = [p for p in products if query in p["name"].lower()]
    return jsonify(filtered), 200


# ---------------------------
# MAIN
# ---------------------------
if __name__ == "__main__":
    app.run(debug=True)
