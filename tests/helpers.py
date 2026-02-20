import importlib.util
import os
import pathlib
import sys
import types
import uuid


def ensure_boto3_stubs() -> None:
    try:
        import boto3  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    boto3_mod = types.ModuleType("boto3")
    boto3_mod.resource = lambda *args, **kwargs: None
    boto3_mod.client = lambda *args, **kwargs: None
    sys.modules["boto3"] = boto3_mod

    conditions_mod = types.ModuleType("boto3.dynamodb.conditions")

    class Attr:
        def __init__(self, name):
            self.name = name

        def eq(self, value):
            return ("eq", self.name, value)

    class Key:
        def __init__(self, name):
            self.name = name

        def eq(self, value):
            return ("eq", self.name, value)

    conditions_mod.Attr = Attr
    conditions_mod.Key = Key

    sys.modules["boto3.dynamodb"] = types.ModuleType("boto3.dynamodb")
    sys.modules["boto3.dynamodb.conditions"] = conditions_mod


def load_lambda_module(relative_path: str):
    ensure_boto3_stubs()
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    full_path = repo_root / relative_path
    module_name = f"testmod_{full_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, full_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module
