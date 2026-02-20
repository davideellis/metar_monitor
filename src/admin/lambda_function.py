import json
import os

import boto3
from boto3.dynamodb.conditions import Attr

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
        "body": json.dumps(payload),
    }


def authorized(event) -> bool:
    configured = os.getenv("ADMIN_TOKEN", "")
    if not configured:
        return False
    headers = event.get("headers") or {}
    incoming = headers.get("x-admin-token") or headers.get("X-Admin-Token") or ""
    return incoming == configured


def list_stations(table) -> list[dict]:
    result = table.scan(ProjectionExpression="station_id, enabled")
    items = result.get("Items", [])
    items.sort(key=lambda i: i.get("station_id", ""))
    return items


def add_station(table, body: dict) -> dict:
    station_id = str(body.get("station_id", "")).strip().upper()
    enabled = bool(body.get("enabled", True))
    if not station_id:
        return {"error": "station_id is required"}
    table.put_item(Item={"station_id": station_id, "enabled": enabled})
    return {"ok": True, "station_id": station_id, "enabled": enabled}


def delete_station(table, station_id: str) -> dict:
    sid = station_id.strip().upper()
    if not sid:
        return {"error": "station_id is required"}
    table.delete_item(Key={"station_id": sid})
    return {"ok": True, "station_id": sid}


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return response(200, {})

    if not authorized(event):
        return response(401, {"error": "Unauthorized"})

    table = dynamodb.Table(os.environ["STATIONS_TABLE"])
    path_params = event.get("pathParameters") or {}

    try:
        if method == "GET":
            items = list_stations(table)
            return response(200, {"count": len(items), "items": items})

        if method == "POST":
            body = json.loads(event.get("body") or "{}")
            result = add_station(table, body)
            if "error" in result:
                return response(400, result)
            return response(200, result)

        if method == "DELETE":
            station_id = path_params.get("station_id", "")
            result = delete_station(table, station_id)
            if "error" in result:
                return response(400, result)
            return response(200, result)

        return response(405, {"error": "Method not allowed"})
    except Exception as exc:  # noqa: BLE001
        return response(500, {"error": str(exc)})
