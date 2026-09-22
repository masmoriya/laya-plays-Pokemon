import argparse

import pytest

from jpp.live_cli import add_parser
from jpp.live_models import prepare_models, startup_requested


@pytest.mark.parametrize("provider,restored,choice,expected", [
    ("laya", False, None, True),
    ("laya", True, False, False),
    ("jev", False, None, False),
    ("jev", True, None, True),
    ("jev", False, True, True),
])
def test_startup_choice_overrides_checkpoint(provider, restored, choice, expected):
    assert startup_requested(provider, restored, choice) is expected


def test_explicit_nonlocal_modes(monkeypatch):
    monkeypatch.setenv("JPP_LOCAL_VLM", "1")
    monkeypatch.setenv("LAYA_VISION", "1")
    assert prepare_models("laya", "off") == "laya"
    assert __import__("os").environ["JPP_LOCAL_VLM"] == "0"
    assert __import__("os").environ["LAYA_VISION"] == "0"


def test_live_options():
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers())
    args = parser.parse_args(["live", "--rom", "game.gbc", "--manual", "--vision", "local"])
    assert args.manual is True
    assert args.vision == "local"


def test_local_reuses_healthy_server(monkeypatch):
    from laya_runtime.client import ModelClient
    monkeypatch.setenv("JPP_LOCAL_VLM", "0")
    monkeypatch.setenv("LAYA_VISION", "0")
    monkeypatch.setattr(ModelClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("must reuse server"))
    assert prepare_models("laya") == "laya"


def test_local_starts_with_configured_interpreter(monkeypatch):
    from laya_runtime.client import ModelClient
    monkeypatch.setenv("JPP_LOCAL_VLM", "0")
    monkeypatch.setenv("LAYA_VISION", "0")
    monkeypatch.setenv("LAYA_VLM_PYTHON", "/dedicated/python")
    calls = []
    def health(self):
        if not calls:
            raise ConnectionError("offline")
        return {"status": "ok"}
    monkeypatch.setattr(ModelClient, "health", health)
    monkeypatch.setattr("subprocess.run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    prepare_models("laya")
    assert calls[0][0][0] == "/dedicated/python"
    assert calls[0][1] == {"check": True, "timeout": 150}
