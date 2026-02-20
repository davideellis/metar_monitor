from tests.helpers import load_lambda_module


def test_parse_limit_defaults_and_clamps():
    history = load_lambda_module("src/history/lambda_function.py")
    assert history.parse_limit(None, 168) == 168
    assert history.parse_limit("bad", 168) == 168
    assert history.parse_limit("0", 168) == 1
    assert history.parse_limit("1000", 168) == 500


def test_options_returns_cors_headers():
    history = load_lambda_module("src/history/lambda_function.py")
    event = {"requestContext": {"http": {"method": "OPTIONS"}}}
    result = history.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert "Access-Control-Allow-Origin" in result["headers"]
