from tests.helpers import load_lambda_module


def test_authorized_accepts_token_case_variants(monkeypatch):
    admin = load_lambda_module("src/admin/lambda_function.py")
    monkeypatch.setenv("ADMIN_TOKEN", "abc123")

    lower = {"headers": {"x-admin-token": "abc123"}}
    upper = {"headers": {"X-Admin-Token": "abc123"}}
    wrong = {"headers": {"x-admin-token": "nope"}}

    assert admin.authorized(lower) is True
    assert admin.authorized(upper) is True
    assert admin.authorized(wrong) is False


def test_add_station_rejects_invalid_notify_on():
    admin = load_lambda_module("src/admin/lambda_function.py")
    result = admin.add_station({"station_id": "KJWY", "notify_on": "bad"})
    assert result["error"] == "notify_on must be error|empty|both"


def test_add_station_upserts_with_normalized_values(monkeypatch):
    admin = load_lambda_module("src/admin/lambda_function.py")
    captured = {}

    class FakeTable:
        def put_item(self, Item):
            captured["item"] = Item

    monkeypatch.setattr(admin, "stations_table", lambda: FakeTable())

    result = admin.add_station(
        {
            "station_id": "kjwy",
            "owner_id": "owner-1",
            "notify_on": "error",
            "cooldown_minutes": 15,
            "enabled": False,
            "alerts_enabled": False,
        }
    )

    assert result["ok"] is True
    assert captured["item"]["station_id"] == "KJWY"
    assert captured["item"]["notify_on"] == "error"
    assert captured["item"]["cooldown_minutes"] == 15
    assert captured["item"]["enabled"] is False
    assert captured["item"]["alerts_enabled"] is False
