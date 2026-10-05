import math
from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/")
def home():
    return jsonify(service="Game Night Deal Tracker", status="running")


@app.get("/discount")
def discount():
    try:
        price = float(request.args["price"])
        percent = float(request.args["percent"])
    except (KeyError, ValueError):
        return jsonify(error="price and percent are required numbers"), 400

    if not (math.isfinite(price) and math.isfinite(percent)) or price < 0 or not 0 <= percent <= 100:
        return jsonify(error="price must be 0 or more and percent must be from 0 to 100"), 400

    sale_price = round(price * (1 - percent / 100), 2)
    return jsonify(price=price, percent=percent, sale_price=sale_price), 200


@app.get("/docs")
def docs():
    return """<!doctype html>
<html><head><title>API Docs</title>
<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse}
td,th{border:1px solid #999;padding:8px;text-align:left;vertical-align:top}</style></head>
<body><h1>Game Night Deal Tracker API</h1>
<table>
<tr><th>Endpoint</th><th>Expects</th><th>Returns</th></tr>
<tr><td>GET /</td><td>nothing</td><td>200 with the service name and "running"</td></tr>
<tr><td>GET /discount</td><td>price: a number 0 or more<br>percent: a number from 0 to 100</td>
<td>200 with price, percent, and sale_price, or 400 with an error message</td></tr>
<tr><td>GET /docs</td><td>nothing</td><td>this page</td></tr>
</table></body></html>"""


if __name__ == "__main__":
    app.run(debug=True)
