import json

from tests.helpers import load_lambda_module


def test_filter_alert_events_drops_empty_when_disabled():
    collector = load_lambda_module("src/collector/lambda_function.py")
    payload = [
        {"station_id": "KJWY", "status": "empty"},
        {"station_id": "KJWY", "status": "error"},
    ]
    filtered = collector.filter_alert_events(payload, alert_on_empty=False)
    assert filtered == [{"station_id": "KJWY", "status": "error"}]


def test_lambda_handler_marks_stale_station_as_error(monkeypatch):
    collector = load_lambda_module("src/collector/lambda_function.py")

    monkeypatch.setenv("METARS_TABLE", "metars")
    monkeypatch.setenv("RUNS_TABLE", "runs")
    monkeypatch.setenv("ROUTER_EVENT_BUS", "default")
    monkeypatch.setenv("ALERT_ON_EMPTY", "true")
    monkeypatch.setenv("STALE_THRESHOLD_HOURS", "2")

    monkeypatch.setattr(collector, "utc_now_iso", lambda: "2026-02-20T10:00:00+00:00")
    monkeypatch.setattr(
        collector,
        "get_station_configs",
        lambda: [
            {
                "station_id": "KJWY",
                "owner_id": "owner-1",
                "notify_on": "both",
                "cooldown_minutes": 60,
                "alerts_enabled": True,
            }
        ],
    )
    monkeypatch.setattr(collector, "build_url", lambda station_ids: "https://example.com")
    monkeypatch.setattr(collector, "fetch_xml", lambda url: "<response/>")
    monkeypatch.setattr(
        collector,
        "parse_metar_xml",
        lambda body: [
            {
                "station_id": "KJWY",
                "observation_time": "2026-02-20T07:30:00+00:00",
            }
        ],
    )

    writes = {}
    events = []
    monkeypatch.setattr(collector, "write_metars", lambda **kwargs: None)
    monkeypatch.setattr(collector, "write_run", lambda **kwargs: writes.update(kwargs))
    monkeypatch.setattr(
        collector,
        "publish_station_alert_events",
        lambda station_events, event_bus_name: events.extend(station_events),
    )

    result = collector.lambda_handler({}, None)
    body = json.loads(result["body"])

    assert result["statusCode"] == 200
    assert body["status"] == "ok"
    assert writes["status"] == "error"
    assert events and events[0]["status"] == "error"


def test_lambda_handler_empty_result_without_empty_alert(monkeypatch):
    collector = load_lambda_module("src/collector/lambda_function.py")

    monkeypatch.setenv("METARS_TABLE", "metars")
    monkeypatch.setenv("RUNS_TABLE", "runs")
    monkeypatch.setenv("ROUTER_EVENT_BUS", "default")
    monkeypatch.setenv("ALERT_ON_EMPTY", "false")

    monkeypatch.setattr(collector, "utc_now_iso", lambda: "2026-02-20T10:00:00+00:00")
    monkeypatch.setattr(
        collector,
        "get_station_configs",
        lambda: [
            {
                "station_id": "KJWY",
                "owner_id": "owner-1",
                "notify_on": "both",
                "cooldown_minutes": 60,
                "alerts_enabled": True,
            }
        ],
    )
    monkeypatch.setattr(collector, "build_url", lambda station_ids: "https://example.com")
    monkeypatch.setattr(collector, "fetch_xml", lambda url: "<response/>")
    monkeypatch.setattr(collector, "parse_metar_xml", lambda body: [])

    writes = {}
    published = []
    monkeypatch.setattr(collector, "write_run", lambda **kwargs: writes.update(kwargs))
    monkeypatch.setattr(
        collector,
        "publish_station_alert_events",
        lambda station_events, event_bus_name: published.extend(station_events),
    )

    result = collector.lambda_handler({}, None)
    body = json.loads(result["body"])

    assert result["statusCode"] == 200
    assert body["status"] == "empty"
    assert writes["status"] == "empty"
    assert published == []
