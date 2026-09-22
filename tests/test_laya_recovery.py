"""Regressions for sidecar version drift and abandoned inference requests."""
import threading

import pytest

from jpp.agent.providers.laya_provider import LayaProvider
from jpp.laya_sidecar import InferenceBusy, LayaService


def test_health_rejects_old_service_before_resuming_game(monkeypatch):
    provider = LayaProvider()
    monkeypatch.setattr(provider, '_health_request', lambda: {'status': 'ok'})
    with pytest.raises(RuntimeError, match='Restart the Laya sidecar'):
        provider.health()


def test_inference_timeout_does_not_resubmit(monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(kwargs['timeout'])
        raise TimeoutError('timed out')

    monkeypatch.setattr('urllib.request.urlopen', timeout)
    with pytest.raises(RuntimeError, match='exceeded 30s'):
        LayaProvider().decide_tactical({}, {'a': 'Confirm', 'b': 'Cancel'})
    assert calls == [30.0]


def test_busy_inference_is_rejected_without_queueing():
    service = object.__new__(LayaService)
    service._predict_lock = threading.Lock()
    service._predict_lock.acquire()
    try:
        with pytest.raises(InferenceBusy):
            service.decide({}, {'a': 'Confirm', 'b': 'Cancel'})
    finally:
        service._predict_lock.release()


def test_context_failure_releases_worker(monkeypatch):
    service = object.__new__(LayaService)
    service._predict_lock = threading.Lock()
    service.agent = object()

    def fail(*args):
        raise ValueError('context too large')

    monkeypatch.setattr('jpp.agent.tactical_context.pack_context', fail)
    with pytest.raises(ValueError, match='context too large'):
        service.decide({}, {'a': 'Confirm', 'b': 'Cancel'})
    assert not service._predict_lock.locked()


def test_health_probe_keeps_short_deadline(monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(kwargs['timeout'])
        raise TimeoutError('timed out')

    monkeypatch.setattr('urllib.request.urlopen', timeout)
    with pytest.raises(RuntimeError, match='sidecar unavailable'):
        LayaProvider(timeout=30).health()
    assert calls == [3.0]
