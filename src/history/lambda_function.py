import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key


dynamodb = boto3.resource("dynamodb")


def cors_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def response(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": cors_headers(),
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


def parse_limit(value: str | None, default_value: int) -> int:
    if not value:
        return default_value
    try:
        limit = int(value)
        return max(1, min(limit, 500))
    except ValueError:
        return default_value


def get_runs(limit: int) -> list[dict]:
    runs_table = dynamodb.Table(os.environ["RUNS_TABLE"])
    result = runs_table.query(
        KeyConditionExpression=Key("pk").eq("RUN"),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = result.get("Items", [])
    items.reverse()
    return items


def get_metars(station_id: str, limit: int) -> list[dict]:
    metars_table = dynamodb.Table(os.environ["METARS_TABLE"])
    result = metars_table.query(
        KeyConditionExpression=Key("station_id").eq(station_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = result.get("Items", [])
    items.reverse()
    return items


def lambda_handler(event, context):
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 200, "headers": cors_headers(), "body": ""}

    params = event.get("queryStringParameters") or {}
    data_type = (params.get("type") or "runs").lower()
    default_station = os.getenv("DEFAULT_STATION", "KJWY")
    station = (params.get("station") or default_station).upper()
    limit = parse_limit(params.get("limit"), default_value=168)

    try:
        if data_type == "metars":
            items = get_metars(station_id=station, limit=limit)
            return response(
                200,
                {
                    "type": "metars",
                    "station": station,
                    "count": len(items),
                    "items": items,
                },
            )

        items = get_runs(limit=limit)
        return response(200, {"type": "runs", "count": len(items), "items": items})
    except Exception as exc:  # noqa: BLE001
        return response(500, {"error": str(exc)})
