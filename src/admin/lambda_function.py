import base64
import hashlib
import hmac
import json
import os
import secrets
import time
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
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
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


def stations_table():
    return dynamodb.Table(os.environ["STATIONS_TABLE"])


def owners_table():
    return dynamodb.Table(os.environ["OWNERS_TABLE"])


def admins_table():
    return dynamodb.Table(os.environ["ADMINS_TABLE"])


def now_epoch() -> int:
    return int(time.time())


def token_secret() -> str:
    return os.getenv("ADMIN_SESSION_SECRET", "").strip() or "unsafe-dev-secret"


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def password_hash(password: str, salt_hex: str, iterations: int) -> str:
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
    return raw.hex()


def create_password_fields(password: str) -> dict:
    salt_hex = secrets.token_hex(16)
    iterations = 200_000
    return {
        "password_salt": salt_hex,
        "password_iterations": iterations,
        "password_hash": password_hash(password, salt_hex, iterations),
    }


def verify_password(password: str, item: dict) -> bool:
    try:
        expected = str(item["password_hash"])
        salt_hex = str(item["password_salt"])
        iterations = int(item.get("password_iterations", 200_000))
    except (KeyError, ValueError, TypeError):
        return False
    actual = password_hash(password, salt_hex, iterations)
    return hmac.compare_digest(expected, actual)


def new_session_token(username: str, ttl_minutes: int = 480) -> tuple[str, int]:
    exp = now_epoch() + (ttl_minutes * 60)
    payload = {"username": username, "exp": exp}
    payload_part = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(token_secret().encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    token = f"{payload_part}.{b64url_encode(sig)}"
    return token, exp


def parse_bearer_token(headers: dict) -> str:
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return ""
    return auth.split(" ", 1)[1].strip()


def verify_session_token(token: str) -> str:
    if "." not in token:
        return ""
    payload_part, sig_part = token.split(".", 1)
    expected_sig = hmac.new(
        token_secret().encode("utf-8"),
        payload_part.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(b64url_encode(expected_sig), sig_part):
        return ""
    try:
        payload = json.loads(b64url_decode(payload_part).decode("utf-8"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return ""
    if now_epoch() >= int(payload.get("exp", 0)):
        return ""
    return str(payload.get("username", "")).strip()


def is_bootstrapped() -> bool:
    resp = admins_table().scan(Limit=1, ProjectionExpression="username")
    return bool(resp.get("Items"))


def get_admin(username: str) -> dict:
    if not username:
        return {}
    resp = admins_table().get_item(Key={"username": username})
    return resp.get("Item", {})


def bootstrap_admin(body: dict) -> dict:
    if is_bootstrapped():
        return {"error": "admin user already exists"}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not username or not password:
        return {"error": "username and password are required"}
    if len(password) < 10:
        return {"error": "password must be at least 10 characters"}
    fields = create_password_fields(password)
    admins_table().put_item(
        Item={
            "username": username,
            **fields,
            "updated_at_epoch": now_epoch(),
        }
    )
    token, exp = new_session_token(username)
    return {"ok": True, "bootstrapped": True, "token": token, "expires_at_epoch": exp}


def login(body: dict) -> dict:
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not username or not password:
        return {"error": "username and password are required"}
    item = get_admin(username)
    if not item or not verify_password(password, item):
        return {"error": "invalid credentials"}
    token, exp = new_session_token(username)
    return {"ok": True, "token": token, "expires_at_epoch": exp}


def request_password_reset(body: dict) -> dict:
    username = str(body.get("username", "")).strip()
    if not username:
        return {"error": "username is required"}
    item = get_admin(username)
    if not item:
        return {"error": "unknown username"}
    reset_code = f"{secrets.randbelow(1_000_000):06d}"
    code_fields = create_password_fields(reset_code)
    expires_at = now_epoch() + 1800
    admins_table().update_item(
        Key={"username": username},
        UpdateExpression=(
            "SET reset_hash=:h, reset_salt=:s, reset_iterations=:i, "
            "reset_expires_epoch=:e, updated_at_epoch=:u"
        ),
        ExpressionAttributeValues={
            ":h": code_fields["password_hash"],
            ":s": code_fields["password_salt"],
            ":i": code_fields["password_iterations"],
            ":e": expires_at,
            ":u": now_epoch(),
        },
    )
    return {"ok": True, "username": username, "reset_code": reset_code, "expires_at_epoch": expires_at}


def confirm_password_reset(body: dict) -> dict:
    username = str(body.get("username", "")).strip()
    reset_code = str(body.get("reset_code", "")).strip()
    new_password = str(body.get("new_password", ""))
    if not username or not reset_code or not new_password:
        return {"error": "username, reset_code, and new_password are required"}
    if len(new_password) < 10:
        return {"error": "new_password must be at least 10 characters"}
    item = get_admin(username)
    if not item:
        return {"error": "unknown username"}
    if now_epoch() > int(item.get("reset_expires_epoch", 0)):
        return {"error": "reset code expired"}
    reset_ok = verify_password(
        reset_code,
        {
            "password_hash": item.get("reset_hash", ""),
            "password_salt": item.get("reset_salt", ""),
            "password_iterations": item.get("reset_iterations", 200_000),
        },
    )
    if not reset_ok:
        return {"error": "invalid reset code"}
    pw_fields = create_password_fields(new_password)
    admins_table().update_item(
        Key={"username": username},
        UpdateExpression=(
            "SET password_hash=:h, password_salt=:s, password_iterations=:i, updated_at_epoch=:u "
            "REMOVE reset_hash, reset_salt, reset_iterations, reset_expires_epoch"
        ),
        ExpressionAttributeValues={
            ":h": pw_fields["password_hash"],
            ":s": pw_fields["password_salt"],
            ":i": pw_fields["password_iterations"],
            ":u": now_epoch(),
        },
    )
    return {"ok": True, "username": username}


def require_auth(event: dict) -> str:
    headers = event.get("headers") or {}
    token = parse_bearer_token(headers)
    return verify_session_token(token)


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

    params = event.get("queryStringParameters") or {}
    kind = (params.get("type") or "stations").lower()
    path_params = event.get("pathParameters") or {}

    try:
        if method == "POST":
            body = json.loads(event.get("body") or "{}")
            action = str(body.get("action", "")).lower()
            if action == "bootstrap":
                result = bootstrap_admin(body)
                return response(400 if "error" in result else 200, result)
            if action == "login":
                result = login(body)
                return response(401 if "error" in result else 200, result)
            if action == "request_reset":
                result = request_password_reset(body)
                return response(400 if "error" in result else 200, result)
            if action == "confirm_reset":
                result = confirm_password_reset(body)
                return response(400 if "error" in result else 200, result)

        username = require_auth(event)
        if not username:
            return response(401, {"error": "Unauthorized"})

        if method == "GET":
            if kind == "owners":
                items = list_owners()
                return response(200, {"type": "owners", "count": len(items), "items": items, "user": username})
            items = list_stations()
            return response(200, {"type": "stations", "count": len(items), "items": items, "user": username})

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
