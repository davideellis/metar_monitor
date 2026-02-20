from tests.helpers import load_lambda_module


def test_parse_notify_on_defaults_to_both():
    router = load_lambda_module("src/router/lambda_function.py")
    assert router.parse_notify_on("error") == "error"
    assert router.parse_notify_on("empty") == "empty"
    assert router.parse_notify_on("bad-value") == "both"


def test_should_notify_policy():
    router = load_lambda_module("src/router/lambda_function.py")
    assert router.should_notify("error", "both") is True
    assert router.should_notify("empty", "both") is True
    assert router.should_notify("error", "error") is True
    assert router.should_notify("empty", "error") is False
    assert router.should_notify("ok", "both") is False


def test_lambda_handler_skips_invalid_event():
    router = load_lambda_module("src/router/lambda_function.py")
    result = router.lambda_handler({"detail": {"status": "ok", "station_id": "KJWY"}}, None)
    assert result["ok"] is True
    assert result["skipped"] == "invalid-event"
