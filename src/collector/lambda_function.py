import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Attr

BASE_URL = "https://aviationweather.gov/api/data/metar"
dynamodb = boto3.resource("dynamodb")
events = boto3.client("events")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc_iso(iso_str: str) -> datetime:
    normalized = iso_str.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def expiration_from_iso(iso_str: str, days: int) -> int:
    dt = parse_utc_iso(iso_str)
    return int((dt + timedelta(days=days)).timestamp())


def expiration_from_now(days: int) -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


def get_retention_days(env_name: str, default_value: int) -> int:
    raw = os.getenv(env_name, str(default_value))
    try:
        return max(1, int(raw))
    except ValueError:
        return default_value


def get_station_configs() -> list[dict]:
    stations_table_name = os.getenv("STATIONS_TABLE", "")
    if stations_table_name:
        stations_table = dynamodb.Table(stations_table_name)
        result = stations_table.scan(
            ProjectionExpression=(
                "station_id, enabled, owner_id, notify_on, cooldown_minutes, alerts_enabled"
            ),
            FilterExpression=Attr("enabled").eq(True),
        )
        items = result.get("Items", [])
        configs = []
        for i in items:
            station_id = str(i.get("station_id", "")).strip().upper()
            if not station_id:
                continue
            configs.append(
                {
                    "station_id": station_id,
                    "owner_id": i.get("owner_id", ""),
                    "notify_on": str(i.get("notify_on", "both")).lower(),
                    "cooldown_minutes": int(i.get("cooldown_minutes", 60)),
                    "alerts_enabled": bool(i.get("alerts_enabled", True)),
                }
            )
        if configs:
            configs.sort(key=lambda x: x["station_id"])
            return configs

    raw = os.getenv("STATION_IDS", "KJWY")
    return [
        {
            "station_id": x.strip().upper(),
            "owner_id": "",
            "notify_on": "both",
            "cooldown_minutes": 60,
            "alerts_enabled": True,
        }
        for x in raw.split(",")
        if x.strip()
    ]


def build_url(station_ids: list[str]) -> str:
    hours = os.getenv("LOOKBACK_HOURS", "2.5")
    query = urllib.parse.urlencode(
        {
            "format": "xml",
            "hours": hours,
            "ids": ",".join(station_ids),
        }
    )
    return f"{BASE_URL}?{query}"


def fetch_xml(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def parse_metar_xml(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    metars = []

    for metar in root.findall(".//METAR"):
        station_id = metar.findtext("station_id")
        observation_time = metar.findtext("observation_time")

        if not station_id or not observation_time:
            continue

        metars.append(
            {
                "station_id": station_id,
                "observation_time": observation_time,
                "temp_c": metar.findtext("temp_c"),
                "dewpoint_c": metar.findtext("dewpoint_c"),
                "wind_dir_degrees": metar.findtext("wind_dir_degrees"),
                "wind_speed_kt": metar.findtext("wind_speed_kt"),
                "visibility_statute_mi": metar.findtext("visibility_statute_mi"),
                "altim_in_hg": metar.findtext("altim_in_hg"),
                "flight_category": metar.findtext("flight_category"),
                "raw_text": metar.findtext("raw_text"),
            }
        )

    return metars


def write_metars(
    metars_table_name: str,
    metars: list[dict],
    collected_at: str,
    retention_days: int,
) -> None:
    table = dynamodb.Table(metars_table_name)
    with table.batch_writer(overwrite_by_pkeys=["station_id", "observation_time"]) as batch:
        for m in metars:
            try:
                expires_at = expiration_from_iso(m["observation_time"], retention_days)
            except ValueError:
                expires_at = expiration_from_now(retention_days)
            batch.put_item(
                Item={
                    "station_id": m["station_id"],
                    "observation_time": m["observation_time"],
                    "collected_at": collected_at,
                    "expires_at": expires_at,
                    "temp_c": m.get("temp_c"),
                    "dewpoint_c": m.get("dewpoint_c"),
                    "wind_dir_degrees": m.get("wind_dir_degrees"),
                    "wind_speed_kt": m.get("wind_speed_kt"),
                    "visibility_statute_mi": m.get("visibility_statute_mi"),
                    "altim_in_hg": m.get("altim_in_hg"),
                    "flight_category": m.get("flight_category"),
                    "raw_text": m.get("raw_text"),
                }
            )


def write_run(
    runs_table_name: str,
    checked_at_utc: str,
    status: str,
    station_ids: list[str],
    source_url: str,
    metar_count: int,
    retention_days: int,
    error_message: str | None = None,
) -> None:
    table = dynamodb.Table(runs_table_name)
    item = {
        "pk": "RUN",
        "checked_at_utc": checked_at_utc,
        "status": status,
        "station_ids": station_ids,
        "source_url": source_url,
        "metar_count": metar_count,
        "expires_at": expiration_from_now(retention_days),
    }

    if error_message:
        item["error_message"] = error_message

    table.put_item(Item=item)


def publish_station_alert_events(station_events: list[dict], event_bus_name: str) -> None:
    if not station_events:
        return

    entries = [
        {
            "Source": "metar.monitor",
            "DetailType": "station-alert",
            "EventBusName": event_bus_name,
            "Detail": json.dumps(e),
        }
        for e in station_events
    ]
    events.put_events(Entries=entries)


def station_alert_events(
    station_configs: list[dict],
    checked_at: str,
    source_url: str,
    status_by_station: dict[str, str],
    error_message: str = "",
) -> list[dict]:
    payloads = []
    for cfg in station_configs:
        sid = cfg["station_id"]
        status = status_by_station.get(sid, "empty")
        if status == "ok":
            continue
        payloads.append(
            {
                "checked_at_utc": checked_at,
                "station_id": sid,
                "status": status,
                "source_url": source_url,
                "error_message": error_message,
                "owner_id": cfg.get("owner_id", ""),
                "notify_on": cfg.get("notify_on", "both"),
                "cooldown_minutes": cfg.get("cooldown_minutes", 60),
                "alerts_enabled": cfg.get("alerts_enabled", True),
            }
        )
    return payloads


def lambda_handler(event, context):
    checked_at = utc_now_iso()
    station_configs = get_station_configs()
    station_ids = [c["station_id"] for c in station_configs]
    source_url = build_url(station_ids)
    metars_table = os.environ["METARS_TABLE"]
    runs_table = os.environ["RUNS_TABLE"]
    alert_on_empty = os.getenv("ALERT_ON_EMPTY", "true").lower() == "true"
    router_event_bus = os.getenv("ROUTER_EVENT_BUS", "default")
    metar_retention_days = get_retention_days("METAR_RETENTION_DAYS", 30)
    run_retention_days = get_retention_days("RUN_RETENTION_DAYS", 30)

    try:
        xml_body = fetch_xml(source_url)
        metars = parse_metar_xml(xml_body)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        write_run(
            runs_table_name=runs_table,
            checked_at_utc=checked_at,
            status="error",
            station_ids=station_ids,
            source_url=source_url,
            metar_count=0,
            retention_days=run_retention_days,
            error_message=err,
        )
        publish_station_alert_events(
            station_alert_events(
                station_configs=station_configs,
                checked_at=checked_at,
                source_url=source_url,
                status_by_station={sid: "error" for sid in station_ids},
                error_message=err,
            ),
            event_bus_name=router_event_bus,
        )
        return {
            "statusCode": 502,
            "body": json.dumps({"status": "error", "error": err, "checked_at_utc": checked_at}),
        }

    if not metars:
        write_run(
            runs_table_name=runs_table,
            checked_at_utc=checked_at,
            status="empty",
            station_ids=station_ids,
            source_url=source_url,
            metar_count=0,
            retention_days=run_retention_days,
        )
        if alert_on_empty:
            publish_station_alert_events(
                station_alert_events(
                    station_configs=station_configs,
                    checked_at=checked_at,
                    source_url=source_url,
                    status_by_station={sid: "empty" for sid in station_ids},
                ),
                event_bus_name=router_event_bus,
            )

        return {"statusCode": 200, "body": json.dumps({"status": "empty", "count": 0})}

    metar_counts: dict[str, int] = {sid: 0 for sid in station_ids}
    for m in metars:
        sid = m["station_id"]
        if sid in metar_counts:
            metar_counts[sid] += 1

    station_statuses = {sid: ("ok" if metar_counts.get(sid, 0) > 0 else "empty") for sid in station_ids}
    if alert_on_empty:
        publish_station_alert_events(
            station_alert_events(
                station_configs=station_configs,
                checked_at=checked_at,
                source_url=source_url,
                status_by_station=station_statuses,
            ),
            event_bus_name=router_event_bus,
        )

    write_metars(
        metars_table_name=metars_table,
        metars=metars,
        collected_at=checked_at,
        retention_days=metar_retention_days,
    )
    write_run(
        runs_table_name=runs_table,
        checked_at_utc=checked_at,
        status="ok",
        station_ids=station_ids,
        source_url=source_url,
        metar_count=len(metars),
        retention_days=run_retention_days,
    )

    payload = {
        "status": "ok",
        "checked_at_utc": checked_at,
        "count": len(metars),
        "stations": sorted({m["station_id"] for m in metars}),
    }
    print(json.dumps(payload))
    return {"statusCode": 200, "body": json.dumps(payload)}
