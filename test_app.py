import pytest
from unittest.mock import patch, MagicMock
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _mock_response(status_code, json_data):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_create_order_missing_item_id(client):
    resp = client.post("/orders", json={"quantity": 2})
    assert resp.status_code == 400


@patch("app.requests.post")
def test_create_order_success(mock_post, client):
    mock_post.side_effect = [
        _mock_response(200, {"item_id": "sku-001", "reserved": 2, "remaining": 48}),
        _mock_response(200, {"status": "sent"}),
    ]
    resp = client.post("/orders", json={"item_id": "sku-001", "quantity": 2, "customer": "yatharth"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "confirmed"
    assert data["item_id"] == "sku-001"


@patch("app.requests.post")
def test_create_order_insufficient_stock(mock_post, client):
    mock_post.side_effect = [
        _mock_response(409, {"error": "insufficient stock"}),
    ]
    resp = client.post("/orders", json={"item_id": "sku-003", "quantity": 1})
    assert resp.status_code == 409


@patch("app.requests.post")
def test_create_order_inventory_service_down(mock_post, client):
    import requests as real_requests
    mock_post.side_effect = real_requests.exceptions.ConnectionError("boom")
    resp = client.post("/orders", json={"item_id": "sku-001", "quantity": 1})
    assert resp.status_code == 503


def test_get_order_not_found(client):
    resp = client.get("/orders/does-not-exist")
    assert resp.status_code == 404
