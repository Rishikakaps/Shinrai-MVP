from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from scripts.demo import PREFIX, accept, link, ok, upload

ANALYST = "test-analyst-" + "a" * 32
JUDGE = "test-judge-" + "j" * 32
TOKENS = {
    ANALYST: {"actor": "Test Analyst", "role": "analyst"},
    JUDGE: {"actor": "Test Judge", "role": "judge"},
}


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, TOKENS)
    with TestClient(app, headers={"Authorization": "Bearer " + ANALYST}) as client:
        yield client


@pytest.fixture
def case(client):
    iid = ok(client.post(PREFIX + "/inspections", json={"name": "Test", "site": "Plant A"}))["id"]
    base = {"serial": "SYN-001", "model": "DemoMill X3", "site": "Plant A"}
    asset = ok(
        client.post(
            f"{PREFIX}/inspections/{iid}/assets",
            json={"tag": "CNC-001", **base, "invoice_ref": "INV-001", "payment_ref": "PAY-001"},
        )
    )
    claims = {c["kind"]: c for c in ok(client.get(f"{PREFIX}/inspections/{iid}/claims"))}
    for kind, claim in claims.items():
        claims[kind] = ok(
            client.patch(
                f"{PREFIX}/inspections/{iid}/claims/{claim['id']}/confirmation",
                json={
                    "version": claim["version"],
                    "expected": claim["expected"],
                    "confirmed": True,
                    "reason": "Checked declaration",
                },
            )
        )

    def add(kind, facts, claim_kind, flags=None, confirmed=True, relation="supports"):
        ev = upload(client, iid, kind, "Synthetic original\n" + str(facts))
        if confirmed:
            ev = accept(client, iid, ev, facts, flags)
        link(client, iid, claims[claim_kind]["id"], ev["id"], relation)
        return ev

    def reconcile():
        results = ok(
            client.post(
                f"{PREFIX}/inspections/{iid}/reconcile", json={"reason": "Evaluate all accepted evidence"}
            )
        )
        return {k: next(f for f in results if f["claim_id"] == c["id"]) for k, c in claims.items()}

    return SimpleNamespace(
        client=client,
        iid=iid,
        base=base,
        asset=asset,
        claims=claims,
        add=add,
        reconcile=reconcile,
        url=f"{PREFIX}/inspections/{iid}",
    )
