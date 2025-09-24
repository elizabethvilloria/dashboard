import json, time
from flask import Blueprint, request, jsonify, abort

bp = Blueprint("catalog", __name__)
_CACHE = {"data": None, "t": 0}

def load_catalog():
    if not _CACHE["data"] or time.time() - _CACHE["t"] > 30:
        with open("catalog.json", "r") as f:
            _CACHE["data"] = json.load(f)
        _CACHE["t"] = time.time()
    return _CACHE["data"]

@bp.route("/catalog/cities")
def catalog_cities():
    return jsonify({"cities": load_catalog()["cities"]})

@bp.route("/catalog/todas")
def catalog_todas():
    city_id = request.args.get("city_id")
    cat = load_catalog()
    todas = [t for t in cat["todas"] if not city_id or t["city_id"] == city_id]
    return jsonify({"todas": todas})

@bp.route("/catalog/etrikes")
def catalog_etrikes():
    toda_id = request.args.get("toda_id")
    if not toda_id:
        abort(400, "toda_id is required")
    cat = load_catalog()
    etrikes = [e for e in cat["etrikes"] if e["toda_id"] == toda_id]
    return jsonify({"etrikes": etrikes})
