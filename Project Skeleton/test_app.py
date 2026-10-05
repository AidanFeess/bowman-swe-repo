from app import app

client = app.test_client()


def test_home_is_running():
    r = client.get("/")
    assert r.status_code == 200
    assert r.get_json()["status"] == "running"


def test_valid_discount_works():
    r = client.get("/discount?price=60&percent=25")
    assert r.status_code == 200
    assert r.get_json()["sale_price"] == 45.0


def test_invalid_percent_is_refused():
    r = client.get("/discount?price=60&percent=150")
    assert r.status_code == 400


def test_missing_price_is_refused():
    r = client.get("/discount?percent=25")
    assert r.status_code == 400
