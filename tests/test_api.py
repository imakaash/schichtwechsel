from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from schichtwechsel.agent import api
from schichtwechsel.config import WAREHOUSE

pytestmark = pytest.mark.skipif(not WAREHOUSE.exists(), reason="needs a local warehouse")


def test_session_flow(monkeypatch):
    reply = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="Hallo, frag mich etwas zu den Daten.")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    fake = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: reply))
    )
    monkeypatch.setattr(api, "client", lambda: fake)
    http = TestClient(api.app)

    assert http.get("/health").json()["status"] == "ok"
    sid = http.post("/sessions").json()["session_id"]
    answer = http.post(f"/sessions/{sid}/ask", json={"question": "Hallo", "language": "de"}).json()
    assert answer["text"].startswith("Hallo") and answer["grounded"]
    assert (
        http.post(f"/sessions/{sid}/ask", json={"question": "x", "language": "fr"}).status_code
        == 422
    )
    assert http.delete(f"/sessions/{sid}").json() == {"closed": True}
    assert http.post(f"/sessions/{sid}/ask", json={"question": "x"}).status_code == 404


def test_dashboard_data_by_name_only():
    from schichtwechsel.agent.dashboard import QUERIES

    http = TestClient(api.app)
    for name in QUERIES:
        body = http.get(f"/data/{name}").json()
        assert body["columns"], name
    assert http.get("/data/SELECT%201").status_code == 404


def test_daily_budget_and_question_limit(monkeypatch):
    reply = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="Hallo, frag mich etwas zu den Daten.")],
        usage=SimpleNamespace(input_tokens=100_000, output_tokens=10_000),
    )
    fake = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: reply))
    )
    monkeypatch.setattr(api, "client", lambda: fake)
    monkeypatch.setattr(api, "DAILY_BUDGET_USD", 0.5)
    monkeypatch.setattr(api, "_spent", {})
    http = TestClient(api.app)
    sid = http.post("/sessions").json()["session_id"]
    ask = lambda: http.post(f"/sessions/{sid}/ask", json={"question": "Hallo"})  # noqa: E731
    assert ask().status_code == 200  # costs $0.30
    assert ask().status_code == 200  # $0.60 now, over the budget
    assert ask().status_code == 429

    monkeypatch.setattr(api, "_spent", {})
    monkeypatch.setattr(api, "MAX_QUESTIONS", 2)
    assert ask().status_code == 429  # this session already asked twice


def test_session_endpoints_need_the_token(monkeypatch):
    monkeypatch.setattr(api, "API_TOKEN", "s3cret")
    http = TestClient(api.app)
    assert http.post("/sessions").status_code == 401
    assert http.post("/sessions", headers={"X-SW-Token": "wrong"}).status_code == 401
    assert http.get("/health").status_code == 200  # public data stays open
    assert http.get("/data/meta").status_code == 200
    monkeypatch.setattr(api, "client", lambda: None)
    assert http.post("/sessions", headers={"X-SW-Token": "s3cret"}).status_code == 200
