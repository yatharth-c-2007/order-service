"""
order-service
Creates orders. On each order, calls inventory-service to reserve
stock, then notification-service to confirm. This is the service
that actually exercises east-west traffic between pods, which is
the whole reason the mesh (Istio) matters later — real service-to-
service calls, real failure modes (timeouts, 4xx/5xx propagation).
"""
from flask import Flask, jsonify, request
import os
import uuid
import logging
import requests
from datetime import datetime, timezone

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("order-service")

INVENTORY_URL = os.environ.get("INVENTORY_SERVICE_URL", "http://localhost:5001")
NOTIFICATION_URL = os.environ.get("NOTIFICATION_SERVICE_URL", "http://localhost:5002")
REQUEST_TIMEOUT = float(os.environ.get("DOWNSTREAM_TIMEOUT_SECONDS", "3"))

ORDERS = {}  # order_id -> order dict, in-memory


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok", service="order-service"), 200


@app.route("/orders", methods=["POST"])
def create_order():
    body = request.get_json(silent=True) or {}
    item_id = body.get("item_id")
    quantity = body.get("quantity", 1)
    customer = body.get("customer", "anonymous")

    if not item_id:
        return jsonify(error="item_id is required"), 400

    order_id = str(uuid.uuid4())

    # Step 1: reserve stock via inventory-service
    try:
        inv_resp = requests.post(
            f"{INVENTORY_URL}/inventory/{item_id}/reserve",
            json={"quantity": quantity},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        logger.error("inventory-service call failed: %s", exc)
        return jsonify(error="inventory service unavailable"), 503

    if inv_resp.status_code == 409:
        return jsonify(error="insufficient stock", detail=inv_resp.json()), 409
    if inv_resp.status_code == 404:
        return jsonify(error="item not found", item_id=item_id), 404
    if inv_resp.status_code != 200:
        return jsonify(error="inventory service error", detail=inv_resp.text), 502

    # Step 2: record the order
    order = {
        "order_id": order_id,
        "item_id": item_id,
        "quantity": quantity,
        "customer": customer,
        "status": "confirmed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    ORDERS[order_id] = order

    # Step 3: fire a notification (best-effort — a failure here shouldn't
    # fail the whole order, it just gets logged)
    try:
        requests.post(
            f"{NOTIFICATION_URL}/notify",
            json={
                "order_id": order_id,
                "channel": "email",
                "message": f"Order {order_id} confirmed for {item_id} x{quantity}",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("notification-service call failed (non-fatal): %s", exc)

    return jsonify(order), 201


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    order = ORDERS.get(order_id)
    if not order:
        return jsonify(error="order not found"), 404
    return jsonify(order), 200


@app.route("/orders", methods=["GET"])
def list_orders():
    return jsonify(orders=list(ORDERS.values())), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5003))
    app.run(host="0.0.0.0", port=port)
