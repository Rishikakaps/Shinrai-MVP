import hashlib
import re
import time

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import ANALYST, JUDGE, TOKENS


def login(client, token=ANALYST):
    page = client.get("/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)[1]
    page = client.post("/login", data={"token": token, "nonce": nonce})
    assert page.status_code == 200
    return re.search(r'name="csrf-token" content="([^"]+)"', page.text)[1]


def test_login_and_no_secret_in_template(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        assert c.get("/app", follow_redirects=False).status_code == 303
        csrf = login(c)
        html = c.get("/app").text
        assert csrf in html and ANALYST not in html and JUDGE not in html
        assert 'data-role="analyst"' in html
        assert 'data-actor="Test Analyst"' in html
        assert "/static/v2-app.js" in html and "/static/v2-app.css" in html
        assert re.search(r"/static/v2-app\.js\?v=[0-9a-f]{16}", html)
        assert c.get("/static/v2-app.js").headers["cache-control"] == "no-cache"
        assert c.get("/static/app.js").status_code == 200
        assert c.get("/static/app.css").status_code == 200
        assert "no-store" in c.get("/app").headers["cache-control"]
        with c.app.state.store.connect() as db:
            record = db.execute("SELECT * FROM browser_sessions").fetchone()
            assert record["sid_hash"] == hashlib.sha256(c.cookies["cdi_session"].encode()).hexdigest()
            assert ANALYST not in str(tuple(record))


def test_cookie_flags_and_logout_revocation(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        csrf = login(c)
        assert c.cookies.get("cdi_session")
        assert c.post("/logout").status_code == 403
        assert c.post("/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
        assert c.get("/api/v1/inspections").status_code == 401


def test_login_nonce_and_invalid_token(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        assert c.post("/login", data={"token": ANALYST, "nonce": "bad"}).status_code == 403
        page = c.get("/login")
        nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)[1]
        response = c.post("/login", data={"token": "not-a-key", "nonce": nonce})
        assert response.status_code == 401 and "not recognized" in response.text
        page = c.get("/login")
        nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)[1]
        assert c.post("/login", data={"token": "非ASCII", "nonce": nonce}).status_code == 401


def test_cookie_csrf_and_origin(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        csrf = login(c)
        body = {"name": "Browser", "site": "Plant A"}
        assert c.post("/api/v1/inspections", json=body).status_code == 403
        assert c.post("/api/v1/inspections", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
        assert (
            c.post(
                "/api/v1/inspections",
                json=body,
                headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/v1/inspections",
                json=body,
                headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
            ).status_code
            == 201
        )


def test_judge_session_reads_but_cannot_write(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        csrf = login(c, JUDGE)
        assert 'data-role="judge"' in c.get("/app").text
        assert c.get("/api/v1/inspections").status_code == 200
        assert (
            c.post(
                "/api/v1/demo/prepare", json={"reason": "Not permitted"}, headers={"X-CSRF-Token": csrf}
            ).status_code
            == 403
        )


def test_bearer_clients_still_work_without_csrf(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        assert (
            c.post(
                "/api/v1/inspections",
                json={"name": "API", "site": "Plant A"},
                headers={"Authorization": "Bearer " + ANALYST},
            ).status_code
            == 201
        )
        login(c)
        assert c.get("/api/v1/inspections", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_sessions_persist_but_expire_and_revoke_after_key_rotation(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        login(c)
        sid = c.cookies["cdi_session"]
    with TestClient(create_app(tmp_path, TOKENS)) as restarted:
        restarted.cookies.set("cdi_session", sid)
        assert restarted.get("/api/v1/inspections").status_code == 200
        with restarted.app.state.store.transaction() as db:
            db.execute("UPDATE browser_sessions SET expires=?", (time.time() - 1,))
        assert restarted.get("/api/v1/inspections").status_code == 401
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        login(c)
        sid = c.cookies["cdi_session"]
    with TestClient(
        create_app(tmp_path, {"rotated-key-" + "r" * 32: {"actor": "New analyst", "role": "analyst"}})
    ) as rotated:
        rotated.cookies.set("cdi_session", sid)
        assert rotated.get("/api/v1/inspections").status_code == 401


def test_secure_cookie_when_https(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS), base_url="https://testserver") as c:
        page = c.get("/login")
        nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)[1]
        response = c.post("/login", data={"token": ANALYST, "nonce": nonce}, follow_redirects=False)
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie


def test_trial_is_separate_and_certificate_flow_uses_browser_session(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as c:
        csrf = login(c)
        headers = {"X-CSRF-Token": csrf}
        first = c.post("/api/v1/demo/prepare", json={"reason": "First"}, headers=headers).json()
        second = c.post("/api/v1/demo/prepare", json={"reason": "Second"}, headers=headers).json()
        assert first["id"] != second["id"]
        base = "/api/v1/inspections/" + first["id"]
        before = c.get(base + "/export").json()
        assert sum(f["computed_status"] == "supported" for f in before["findings"]) == 15
        assert sum(f["computed_status"] == "unresolved" for f in before["findings"]) == 3
        asset = next(a for a in before["assets"] if a["tag"] == "CNC-002")
        claim = next(
            x for x in before["claims"] if x["asset_id"] == asset["id"] and x["kind"] == "commissioning"
        )
        pdf = c.get(base + "/demo-certificate/" + asset["id"])
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        ev = c.post(
            base + "/evidence",
            headers=headers,
            data={
                "kind": "commissioning_certificate",
                "source": "Synthetic browser test",
                "captured_at": "2026-01-01T00:00:00Z",
                "reason": "Test actual extraction",
            },
            files={"file": ("certificate.pdf", pdf.content, "application/pdf")},
        ).json()
        ev = c.post(
            base + "/evidence/" + ev["id"] + "/extract", headers=headers, json={"reason": "Read actual PDF"}
        ).json()
        assert ev["facts"]["serial"] == "SYN-002" and ev["confirmed"] is False
        assert not c.get(base + "/export").json()["reconciliation_current"]
        c.post(
            base + "/evidence-links",
            headers=headers,
            json={
                "claim_id": claim["id"],
                "evidence_id": ev["id"],
                "relation": "supports",
                "locator": "page 1",
                "reason": "Correct machine certificate",
            },
        ).raise_for_status()
        findings = c.post(
            base + "/reconcile", headers=headers, json={"reason": "Check unaccepted evidence"}
        ).json()
        assert next(f for f in findings if f["claim_id"] == claim["id"])["computed_status"] == "unresolved"
        c.patch(
            base + "/evidence/" + ev["id"] + "/correction",
            headers=headers,
            json={
                "version": ev["version"],
                "text": ev["text"],
                "facts": ev["facts"],
                "quality_flags": [],
                "confirmed": True,
                "reason": "Analyst checked original",
            },
        ).raise_for_status()
        findings = c.post(
            base + "/reconcile", headers=headers, json={"reason": "Accepted certificate"}
        ).json()
        assert next(f for f in findings if f["claim_id"] == claim["id"])["computed_status"] == "supported"
        after = c.get(base + "/export").json()
        assert len(after["finding_history"]) > len(before["finding_history"])
        assert all(event in after["review_events"] for event in before["review_events"])
        untouched = c.get("/api/v1/inspections/" + second["id"] + "/export").json()
        assert sum(f["computed_status"] == "unresolved" for f in untouched["findings"]) == 3


def test_html_escapes_identity_and_never_embeds_api_key(tmp_path):
    key = "xss-demo-" + "x" * 32
    with TestClient(
        create_app(tmp_path, {key: {"actor": "<script>alert(1)</script>", "role": "analyst"}})
    ) as c:
        login(c, key)
        html = c.get("/app").text
        assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
        assert key not in html


def test_pdf_preview_is_readable_scoped_and_integrity_checked(case):
    import io

    from PIL import Image

    from scripts.demo import pdf_bytes

    ev = case.client.post(
        case.url + "/evidence",
        data={
            "kind": "commissioning_certificate",
            "source": "Synthetic preview",
            "captured_at": "2026-01-01T00:00:00Z",
            "reason": "Preview",
        },
        files={
            "file": ("certificate.pdf", pdf_bytes("serial: SYN-001\ncommissioned: true"), "application/pdf")
        },
    ).json()
    url = case.url + "/evidence/" + ev["id"] + "/preview/"
    preview = case.client.get(url + "1")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.headers["x-pdf-pages"] == "1"
    image = Image.open(io.BytesIO(preview.content))
    assert image.width > 500 and image.height > 500
    assert case.client.get(url + "0").status_code == 422
    assert case.client.get(url + "2").status_code == 422
    assert case.client.get(url.replace(case.iid, "wrong-scope") + "1").status_code == 404
    (case.client.app.state.store.files / ev["sha256"]).write_bytes(b"corrupt")
    assert case.client.get(url + "1").status_code == 409


def test_non_pdf_cannot_use_pdf_preview(case):
    ev = case.add("site_image", case.base, "presence")
    assert case.client.get(case.url + "/evidence/" + ev["id"] + "/preview/1").status_code == 415
