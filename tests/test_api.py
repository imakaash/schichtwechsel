from types import SimpleNamespace

from fastapi.testclient import TestClient

from schichtwechsel.agent import api


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
