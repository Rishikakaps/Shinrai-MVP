"""Read-only consultation persistence/citations. Provider output is explicitly mocked."""

from uuid import uuid4

from fastapi import HTTPException

from tests import test_v2_backend as flows
from tests.conftest import JUDGE

v2 = flows.v2


def ask(v2, key=None, **changes):
    body = {
        "inspection_id": v2.case.iid,
        "physical_asset_id": v2.physical["id"],
        "question": "What commissioning evidence is missing?",
        "reason": "Synthetic analyst consultation",
        **changes,
    }
    return v2.client.post(v2.root + "/chat", json=body, headers={"Idempotency-Key": key or str(uuid4())})


def test_chat_cites_saved_context_and_does_not_change_findings(v2, monkeypatch):
    before = v2.case.reconcile()
    calls = []

    def model(question, context):
        calls.append((question, context))
        return {
            "answer": "Commissioning remains unresolved; review the missing certificate.",
            "source_ids": [context["sources"][0]["id"]],
        }

    monkeypatch.setattr(v2.client.app.state.ai, "consult", model)
    key = str(uuid4())
    r = ask(v2, key)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["provider"] == "gemini" and item["sources"]
    assert ask(v2, key).json()["id"] == item["id"] and len(calls) == 1
    assert len(v2.client.get(v2.root + "/chat").json()) == 1
    after = v2.case.reconcile()
    assert [f["id"] for f in before.values()] == [f["id"] for f in after.values()]


def test_chat_rejects_invented_citation_without_saving(v2, monkeypatch):
    monkeypatch.setattr(
        v2.client.app.state.ai,
        "consult",
        lambda *args: {"answer": "Unsupported answer", "source_ids": ["invented-id"]},
    )
    assert ask(v2).status_code == 502
    assert v2.client.get(v2.root + "/chat").json() == []


def test_chat_provider_failure_does_not_create_a_success_record(v2, monkeypatch):
    def absent(*args):
        raise HTTPException(503, "Google unavailable")

    monkeypatch.setattr(v2.client.app.state.ai, "consult", absent)
    assert ask(v2).status_code == 503
    assert v2.client.get(v2.root + "/chat").json() == []


def test_chat_denies_judge_and_wrong_machine_scope(v2):
    assert v2.client.get(v2.root + "/chat", headers={"Authorization": "Bearer " + JUDGE}).status_code == 403
    r = v2.client.post(
        v2.root + "/chat",
        json={"inspection_id": v2.case.iid, "question": "Not permitted", "reason": "Judge write"},
        headers={"Authorization": "Bearer " + JUDGE, "Idempotency-Key": str(uuid4())},
    )
    assert r.status_code == 403
    assert ask(v2, physical_asset_id="foreign-machine").status_code == 404
