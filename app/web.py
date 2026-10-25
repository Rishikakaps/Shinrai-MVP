"""FastAPI-served browser UI, controlled sign-in, and non-destructive synthetic trial helpers."""

import hashlib
import hmac
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import engine
from app.browser_auth import COOKIE, SESSION_SECONDS
from app.demo_data import certificate_pdf, prepare_trial
from app.models import Asset, Evidence, Inspection, Reason
from app.preview import render_page


def install_ui(app, store, sessions, authenticate):
    base = Path(__file__).parent
    templates = Jinja2Templates(directory=base / "templates")

    def static_asset(name):
        version = hashlib.sha256((base / "static" / name).read_bytes()).hexdigest()[:16]
        return f"/static/{name}?v={version}"

    templates.env.globals["static_asset"] = static_asset
    app.mount("/static", StaticFiles(directory=base / "static"), name="static")
    Actor = Annotated[str, Depends(authenticate)]

    @app.middleware("http")
    async def browser_headers(request, call_next):
        request_id = request.headers.get("X-Request-ID", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
            request_id = uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("uvicorn.error").info(
            "request_id=%s method=%s path=%s status=%s ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            round((time.monotonic() - started) * 1000),
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
            "frame-src 'self' blob:; object-src 'none'; connect-src 'self'; "
            "media-src 'self' blob:; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
        )
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    def login_page(request, error=None, status_code=200):
        nonce = secrets.token_urlsafe(32)
        response = templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"nonce": nonce, "error": error, "next_page": request.query_params.get("next", "/app")},
            status_code=status_code,
        )
        response.set_cookie(
            "cdi_login_nonce",
            nonce,
            max_age=600,
            httponly=True,
            secure=sessions.secure(request),
            samesite="strict",
        )
        return response

    @app.get("/", include_in_schema=False)
    def home(request: Request):
        return RedirectResponse("/app" if sessions.read(request) else "/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def sign_in(request: Request):
        if sessions.read(request):
            target = request.query_params.get("next", "/app")
            return RedirectResponse(
                target if target in {"/app", "/field-test", "/backend-test"} else "/app", status_code=303
            )
        return login_page(request)

    @app.post("/login", include_in_schema=False)
    def submit_login(
        request: Request,
        token: Annotated[str, Form(max_length=512)],
        nonce: Annotated[str, Form(max_length=200)],
        next_page: Annotated[str, Form(max_length=100)] = "/app",
    ):
        cookie = request.cookies.get("cdi_login_nonce", "")
        origin = request.headers.get("origin")
        if (
            not cookie
            or not hmac.compare_digest(cookie.encode(), nonce.encode())
            or (origin and origin.rstrip("/") != str(request.base_url).rstrip("/"))
        ):
            return login_page(request, "This sign-in page expired. Please try again.", 403)
        sid = sessions.issue(token.strip())
        if sid is None:
            return login_page(
                request, "That access key was not recognized. Check the analyst or judge key.", 401
            )
        response = RedirectResponse(
            next_page if next_page in {"/app", "/field-test", "/backend-test"} else "/app", status_code=303
        )
        response.delete_cookie("cdi_login_nonce")
        response.set_cookie(
            COOKIE,
            sid,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=sessions.secure(request),
            samesite="strict",
        )
        return response

    @app.post("/logout", include_in_schema=False)
    def sign_out(request: Request):
        session = sessions.read(request)
        if session is None:
            raise HTTPException(401, "Session expired")
        sessions.validate_write(request, session)
        sessions.revoke(request)
        response = Response(status_code=204)
        response.delete_cookie(COOKIE)
        return response

    @app.get("/app", response_class=HTMLResponse, include_in_schema=False)
    def workspace(request: Request):
        session = sessions.read(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request=request, name="app.html", context={"viewer": session})

    @app.get("/backend-test", response_class=HTMLResponse, include_in_schema=False)
    def backend_verification(request: Request):
        session = sessions.read(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request=request, name="v2_test.html", context={"viewer": session})

    @app.get("/field-test", response_class=HTMLResponse, include_in_schema=False)
    def field_test(request: Request):
        session = sessions.read(request)
        if session is None:
            return RedirectResponse("/login?next=/field-test", status_code=303)
        return templates.TemplateResponse(
            request=request, name="field_test.html", context={"viewer": session}
        )

    @app.post("/api/v1/demo/prepare", response_model=Inspection)
    def new_trial(body: Reason, actor: Actor):
        # This helper only creates a new synthetic inspection. Existing data is never reset.
        return prepare_trial(store, actor)

    @app.get("/api/v1/inspections/{iid}/evidence/{eid}/preview/{page}", dependencies=[Depends(authenticate)])
    def pdf_preview(iid: str, eid: str, page: int):
        if not 1 <= page <= 12:
            raise HTTPException(422, "Choose a page from 1 to 12")
        with store.transaction(write=False) as db:
            item = store.get(db, Evidence, eid, iid)
            if not engine.intact(store, item):
                raise HTTPException(409, "Original integrity check failed")
            if item.media_type != "application/pdf":
                raise HTTPException(415, "Page rendering is available for PDF originals")
        png, pages = render_page(store.files / item.sha256, page)
        return Response(png, media_type="image/png", headers={"X-PDF-Pages": str(pages)})

    @app.get("/api/v1/inspections/{iid}/demo-certificate/{aid}", dependencies=[Depends(authenticate)])
    def sample_certificate(iid: str, aid: str):
        with store.transaction(write=False) as db:
            inspection = store.get(db, Inspection, iid, iid)
            asset = store.get(db, Asset, aid, iid)
        if not inspection.name.startswith("Plant A trial ·"):
            raise HTTPException(422, "Sample certificates are available for fresh synthetic trials only")
        filename = re.sub(r"[^A-Za-z0-9_.-]", "_", asset.tag)[:80] + "-synthetic-certificate.pdf"
        return Response(
            certificate_pdf(asset),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
