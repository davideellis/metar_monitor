import json
import os
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")


def response(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,x-admin-token",
        },
        "body": json.dumps(to_json_safe(payload)),
    }


def to_json_safe(value):
    if isinstance(value, list):
        return [to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: to_json_safe(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def authorized(event) -> bool:
    configured = os.getenv("ADMIN_TOKEN", "")
    if not configured:
        return False
    headers = event.get("headers") or {}
    incoming = headers.get("x-admin-token") or headers.get("X-Admin-Token") or ""
    return incoming == configured


def stations_table():
    return dynamodb.Table(os.environ["STATIONS_TABLE"])


def owners_table():
    return dynamodb.Table(os.environ["OWNERS_TABLE"])


def list_stations() -> list[dict]:
    result = stations_table().scan()
    items = result.get("Items", [])
    items.sort(key=lambda i: i.get("station_id", ""))
    return items


def list_owners() -> list[dict]:
    result = owners_table().scan()
    items = result.get("Items", [])
    items.sort(key=lambda i: i.get("owner_id", ""))
    return items


def add_station(body: dict) -> dict:
    station_id = str(body.get("station_id", "")).strip().upper()
    if not station_id:
        return {"error": "station_id is required"}
    item = {
        "station_id": station_id,
        "enabled": bool(body.get("enabled", True)),
        "owner_id": str(body.get("owner_id", "")).strip(),
        "notify_on": str(body.get("notify_on", "both")).lower(),
        "cooldown_minutes": int(body.get("cooldown_minutes", 60)),
        "alerts_enabled": bool(body.get("alerts_enabled", True)),
    }
    if item["notify_on"] not in {"error", "empty", "both"}:
        return {"error": "notify_on must be error|empty|both"}
    stations_table().put_item(Item=item)
    return {"ok": True, "item": item}


def add_owner(body: dict) -> dict:
    owner_id = str(body.get("owner_id", "")).strip()
    topic_arn = str(body.get("topic_arn", "")).strip()
    if not owner_id:
        return {"error": "owner_id is required"}
    if not topic_arn:
        return {"error": "topic_arn is required"}
    item = {
        "owner_id": owner_id,
        "topic_arn": topic_arn,
        "alerts_enabled": bool(body.get("alerts_enabled", True)),
    }
    owners_table().put_item(Item=item)
    return {"ok": True, "item": item}


def delete_station(station_id: str) -> dict:
    sid = station_id.strip().upper()
    if not sid:
        return {"error": "station_id is required"}
    stations_table().delete_item(Key={"station_id": sid})
    return {"ok": True, "station_id": sid}


def delete_owner(owner_id: str) -> dict:
    oid = owner_id.strip()
    if not oid:
        return {"error": "owner_id is required"}
    owners_table().delete_item(Key={"owner_id": oid})
    return {"ok": True, "owner_id": oid}


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return response(200, {})

    if not authorized(event):
        return response(401, {"error": "Unauthorized"})

    params = event.get("queryStringParameters") or {}
    kind = (params.get("type") or "stations").lower()
    path_params = event.get("pathParameters") or {}

    try:
        if method == "GET":
            if kind == "owners":
                items = list_owners()
                return response(200, {"type": "owners", "count": len(items), "items": items})
            items = list_stations()
            return response(200, {"type": "stations", "count": len(items), "items": items})

        if method == "POST":
            body = json.loads(event.get("body") or "{}")
            result = add_owner(body) if kind == "owners" else add_station(body)
            if "error" in result:
                return response(400, result)
            return response(200, result)

        if method == "DELETE":
            if "owner_id" in path_params:
                result = delete_owner(path_params.get("owner_id", ""))
            else:
                result = delete_station(path_params.get("station_id", ""))
            if "error" in result:
                return response(400, result)
            return response(200, result)

        return response(405, {"error": "Method not allowed"})
    except Exception as exc:  # noqa: BLE001
        return response(500, {"error": str(exc)})
