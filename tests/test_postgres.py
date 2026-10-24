"""Live Postgres integration. Set CDI_TEST_DATABASE_URL to an isolated test database."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Inspection
from scripts.demo import PREFIX, ok
from tests.conftest import ANALYST, TOKENS

pytestmark = pytest.mark.skipif(
    not os.environ.get("CDI_TEST_DATABASE_URL"), reason="Isolated Postgres test DB not configured"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CDI_AUTO_MIGRATE", "true")
    with TestClient(
        create_app(tmp_path, TOKENS, database_url=os.environ["CDI_TEST_DATABASE_URL"]),
        headers={"Authorization": "Bearer " + ANALYST},
    ) as c:
        yield c


def test_postgres_jsonb_and_atomic_audit(case):
    assert case.client.app.state.store.backend == "postgres"
    store = case.client.app.state.store
    with store.transaction(write=False) as db:
        row = db.execute("SELECT data FROM cdi.objects WHERE id=%s", (case.iid,)).fetchone()
        assert isinstance(row["data"], dict)
    assert case.client.get("/ready").json()["database"] == "postgres"
    assert len(ok(case.client.get(case.url + "/review-events"))) >= 14


def test_postgres_versions_and_concurrent_updates(case):
    payload = {
        key: case.asset[key] for key in ("tag", "serial", "model", "site", "invoice_ref", "payment_ref")
    }
    payload.update(version=case.asset["version"], reason="Concurrent declaration correction")

    def update():
        return case.client.patch(case.url + f"/assets/{case.asset['id']}", json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: update(), range(2))) == [200, 409]


def test_postgres_mutation_rollback(case):
    store = case.client.app.state.store
    identifier = str(uuid4())
    with pytest.raises(RuntimeError), store.transaction() as db:
        item = Inspection(id=identifier, inspection_id=identifier, name="Rollback test", site="Synthetic")
        store.save(db, item, "Test Analyst", "Rollback test", "inspection.created")
        raise RuntimeError("abort")
    assert case.client.get(PREFIX + "/inspections/" + identifier).status_code == 404
    with store.transaction(write=False) as db:
        assert (
            db.execute(
                "SELECT count(*) AS n FROM cdi.review_events WHERE entity_id=%s", (identifier,)
            ).fetchone()["n"]
            == 0
        )


def test_postgres_audit_cannot_be_replaced(case):
    store = case.client.app.state.store
    event = ok(case.client.get(case.url + "/review-events"))[0]
    with pytest.raises(Exception, match="immutable"), store.transaction() as db:
        db.execute("UPDATE cdi.review_events SET data=data WHERE id=%s", (event["id"],))


def test_postgres_reader_does_not_wait_on_writer(case):
    store = case.client.app.state.store
    with store.transaction(), ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(case.client.get, case.url).result(timeout=4).status_code == 200


def test_postgres_claim_workflow_and_stale_review(case):
    ev = case.add("site_image", {**case.base, "present": True}, "presence")
    finding = case.reconcile()["presence"]
    assert finding["computed_status"] == "supported"
    ok(
        case.client.patch(
            case.url + f"/evidence/{ev['id']}/correction",
            json={
                "version": ev["version"],
                "text": "Corrected absent observation",
                "facts": {**case.base, "present": False},
                "quality_flags": [],
                "confirmed": True,
                "reason": "Correct observation",
            },
        )
    )
    assert (
        case.client.patch(
            case.url + f"/findings/{finding['id']}/review",
            json={"version": finding["version"], "status": "supported", "reason": "Stale"},
        ).status_code
        == 409
    )
    assert case.reconcile()["presence"]["computed_status"] == "potentially_inconsistent"


def test_postgres_browser_session_and_synthetic_trial(client):
    from tests.test_browser_ui import login

    client.headers.pop("Authorization", None)
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    assert client.post(PREFIX + "/demo/prepare", json={"reason": "Missing CSRF"}).status_code == 403
    inspection = ok(client.post(PREFIX + "/demo/prepare", json={"reason": "Browser trial"}, headers=headers))
    base = PREFIX + "/inspections/" + inspection["id"]
    report = ok(client.get(base + "/export"))
    assert len(report["claims"]) == 18
    assert sum(f["computed_status"] == "supported" for f in report["findings"]) == 15
    asset = next(a for a in report["assets"] if a["tag"] == "CNC-002")
    assert client.get(base + "/demo-certificate/" + asset["id"]).content.startswith(b"%PDF")
    with client.app.state.store.transaction(), ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(client.get, base).result(timeout=4).status_code == 200
    assert client.post("/logout", headers=headers).status_code == 204
    assert client.get(base).status_code == 401
