import json
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")


def now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def parse_notify_on(value: str) -> str:
    v = (value or "both").lower()
    if v in {"error", "empty", "both"}:
        return v
    return "both"


def should_notify(status: str, notify_on: str) -> bool:
    if status not in {"error", "empty"}:
        return False
    if notify_on == "both":
        return True
    return status == notify_on


def get_station(table_name: str, station_id: str) -> dict:
    table = dynamodb.Table(table_name)
    resp = table.get_item(Key={"station_id": station_id})
    return resp.get("Item", {})


def get_owner(table_name: str, owner_id: str) -> dict:
    table = dynamodb.Table(table_name)
    resp = table.get_item(Key={"owner_id": owner_id})
    return resp.get("Item", {})


def in_cooldown(table_name: str, station_id: str, alert_type: str, cooldown_minutes: int) -> bool:
    table = dynamodb.Table(table_name)
    resp = table.get_item(Key={"station_id": station_id, "alert_type": alert_type})
    item = resp.get("Item")
    if not item:
        return False
    last = int(item.get("last_notified_epoch", 0))
    return (now_epoch() - last) < (cooldown_minutes * 60)


def update_cooldown(table_name: str, station_id: str, alert_type: str, cooldown_minutes: int) -> None:
    table = dynamodb.Table(table_name)
    current = now_epoch()
    expires_at = current + int(timedelta(days=30).total_seconds())
    table.put_item(
        Item={
            "station_id": station_id,
            "alert_type": alert_type,
            "last_notified_epoch": current,
            "expires_at": expires_at,
            "cooldown_minutes": cooldown_minutes,
        }
    )


def publish_owner_topic(topic_arn: str, subject: str, message: str, attrs: dict) -> None:
    sns.publish(
        TopicArn=topic_arn,
        Subject=subject[:100],
        Message=message,
        MessageAttributes={
            "station_id": {"DataType": "String", "StringValue": attrs.get("station_id", "")},
            "owner_id": {"DataType": "String", "StringValue": attrs.get("owner_id", "")},
            "status": {"DataType": "String", "StringValue": attrs.get("status", "")},
        },
    )


def lambda_handler(event, context):
    detail = event.get("detail", {})
    station_id = str(detail.get("station_id", "")).upper()
    status = str(detail.get("status", "")).lower()
    checked_at = detail.get("checked_at_utc", "")
    source_url = detail.get("source_url", "")
    error_message = detail.get("error_message", "")

    if not station_id or status not in {"error", "empty"}:
        return {"ok": True, "skipped": "invalid-event"}

    stations_table = os.environ["STATIONS_TABLE"]
    owners_table = os.environ["OWNERS_TABLE"]
    state_table = os.environ["ALERT_STATE_TABLE"]

    station = get_station(stations_table, station_id)
    if not station:
        return {"ok": True, "skipped": "station-not-found"}
    if not bool(station.get("alerts_enabled", True)):
        return {"ok": True, "skipped": "station-alerts-disabled"}

    notify_on = parse_notify_on(str(station.get("notify_on", "both")))
    if not should_notify(status, notify_on):
        return {"ok": True, "skipped": "notify-policy"}

    owner_id = str(station.get("owner_id", "")).strip()
    if not owner_id:
        return {"ok": True, "skipped": "no-owner"}

    owner = get_owner(owners_table, owner_id)
    if not owner:
        return {"ok": True, "skipped": "owner-not-found"}
    if not bool(owner.get("alerts_enabled", True)):
        return {"ok": True, "skipped": "owner-alerts-disabled"}

    topic_arn = owner.get("topic_arn", "")
    if not topic_arn:
        return {"ok": True, "skipped": "no-owner-topic"}

    cooldown_minutes = int(station.get("cooldown_minutes", 60))
    if in_cooldown(state_table, station_id, status, cooldown_minutes):
        return {"ok": True, "skipped": "cooldown"}

    subject = f"METAR {status.upper()} - {station_id}"
    msg = (
        f"Station: {station_id}\n"
        f"Status: {status}\n"
        f"Checked At UTC: {checked_at}\n"
        f"Source URL: {source_url}\n"
        f"Error: {error_message or 'N/A'}\n"
    )

    publish_owner_topic(
        topic_arn,
        subject,
        msg,
        {"station_id": station_id, "owner_id": owner_id, "status": status},
    )
    update_cooldown(state_table, station_id, status, cooldown_minutes)

    return {"ok": True, "notified": True, "station_id": station_id, "owner_id": owner_id}
