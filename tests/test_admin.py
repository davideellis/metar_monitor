import json

from tests.helpers import load_lambda_module


def test_password_hash_and_verify():
    admin = load_lambda_module("src/admin/lambda_function.py")
    fields = admin.create_password_fields("SuperSecurePass1!")
    assert admin.verify_password("SuperSecurePass1!", fields) is True
    assert admin.verify_password("wrong", fields) is False


def test_session_token_roundtrip(monkeypatch):
    admin = load_lambda_module("src/admin/lambda_function.py")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret")
    token, _ = admin.new_session_token("alice", ttl_minutes=5)
    assert admin.verify_session_token(token) == "alice"


def test_bootstrap_then_login(monkeypatch):
    admin = load_lambda_module("src/admin/lambda_function.py")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret")

    class FakeAdmins:
        def __init__(self):
            self.items = {}

        def scan(self, **kwargs):
            if self.items:
                return {"Items": [{"username": next(iter(self.items.keys()))}]}
            return {"Items": []}

        def put_item(self, Item):
            self.items[Item["username"]] = Item

        def get_item(self, Key):
            item = self.items.get(Key["username"])
            return {"Item": item} if item else {}

    fake = FakeAdmins()
    monkeypatch.setattr(admin, "admins_table", lambda: fake)

    bootstrap = admin.bootstrap_admin({"username": "admin", "password": "StrongPass123!"})
    assert bootstrap["ok"] is True
    login = admin.login({"username": "admin", "password": "StrongPass123!"})
    assert login["ok"] is True
    assert "token" in login


def test_add_station_rejects_invalid_notify_on():
    admin = load_lambda_module("src/admin/lambda_function.py")
    result = admin.add_station({"station_id": "KJWY", "notify_on": "bad"})
    assert result["error"] == "notify_on must be error|empty|both"


def test_public_login_action_does_not_require_bearer(monkeypatch):
    admin = load_lambda_module("src/admin/lambda_function.py")
    monkeypatch.setattr(admin, "login", lambda body: {"ok": True, "token": "abc", "expires_at_epoch": 123})
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "queryStringParameters": {},
        "pathParameters": {},
        "headers": {},
        "body": json.dumps({"action": "login", "username": "a", "password": "b"}),
    }
    result = admin.lambda_handler(event, None)
    assert result["statusCode"] == 200
