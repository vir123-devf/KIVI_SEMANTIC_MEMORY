from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app


def test_health_and_ingest_roundtrip():
    init_db()
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}

    user_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    payload = {
        "user_id": user_id,
        "records": [
            {
                "occurred_at": "2026-06-01T09:15:00+00:00",
                "source_app": "slack",
                "raw_asr": "standup is at nine thirty",
                "formatted_text": "Standup is at 9:30.",
            }
        ],
    }
    res = client.post("/ingest", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["episodes_created"] == 1

    episodes = client.get(f"/memories/{user_id}/episodes")
    assert episodes.status_code == 200
    assert len(episodes.json()) == 1

    created = client.post("/memories/fact", json={
        "user_id": user_id, "subject": "manager", "value": "Priya Nair",
    })
    assert created.status_code == 200, created.text
    fact_id = created.json()["id"]
    patched = client.patch(f"/memories/fact/{fact_id}", json={"value": "Alex Chen"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["value"] == "Alex Chen"
    facts = client.get(f"/memories/{user_id}/facts").json()
    active = [f for f in facts if f["status"] == "active"]
    superseded = [f for f in facts if f["status"] == "superseded"]
    assert any(f["value"] == "Alex Chen" for f in active)
    assert any(f["value"] == "Priya Nair" for f in superseded)
