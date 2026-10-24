"""Read models and source-linked JSON/text/PDF review exports."""

import io
import json
from xml.sax.saxutils import escape

from fastapi import Request
from fastapi.responses import PlainTextResponse, Response

from app.models import Asset, FollowUpAction, now
from app.v2_capture import visible_audio
from app.v2_models import (
    AcousticComparison,
    AssetBinding,
    AudioRecording,
    CopilotAnalysis,
    ExtractedCandidate,
    FollowUpContext,
    InterviewSession,
    InvestmentProject,
    InvestmentReview,
    InvestmentTarget,
    Membership,
    PhysicalAsset,
    StatementRecord,
    TranscriptSegment,
)


def make_snapshot(service, db, request, case_id, get_report):
    store = service.store
    case = service.get_case(db, case_id)
    memberships = service.list(db, Membership, case_id)
    analyst = request.state.principal["role"] == "analyst"
    audio = [a for a in service.list(db, AudioRecording, case_id) if visible_audio(request, a)]
    allowed_audio = {a.id for a in audio}
    all_segments = service.list(db, TranscriptSegment, case_id)
    segments = [s for s in all_segments if not s.recording_id or s.recording_id in allowed_audio]
    allowed_segments = {s.id for s in segments}
    hidden_segments = {s.id for s in all_segments} - allowed_segments
    result = {
        "schema_version": "2.0",
        "generated_at": now(),
        "synthetic": case.synthetic,
        "scope": "Attributed inspection and investment review. No automated underwriting, fault diagnosis or independently authenticated issuer check.",
        "case": case,
        "v1_inspections": [get_report(db, m.inspection_id) for m in memberships],
        "physical_assets": service.list(db, PhysicalAsset, case_id),
        "asset_bindings": service.list(db, AssetBinding, case_id),
        "investments": service.list(db, InvestmentProject, case_id),
        "targets": service.list(db, InvestmentTarget, case_id),
        "investment_reviews": service.list(db, InvestmentReview, case_id),
        "follow_ups": [
            {"task": store.get(db, FollowUpAction, c.follow_up_id), "details": c}
            for c in service.list(db, FollowUpContext, case_id)
        ],
        "interviews": service.list(db, InterviewSession, case_id),
        "segments": segments,
        "statements": [
            s
            for s in service.list(db, StatementRecord, case_id)
            if s.source.segment_id not in hidden_segments
        ],
        "audio": audio,
        "comparisons": [
            c
            for c in service.list(db, AcousticComparison, case_id)
            if c.first_id in allowed_audio and c.second_id in allowed_audio
        ],
        "analyses": [
            a for a in service.list(db, CopilotAnalysis, case_id) if a.segment_id in allowed_segments
        ],
        "candidates": service.list(db, ExtractedCandidate, case_id) if analyst else [],
        "audit_events": [e for m in memberships for e in store.events(db, m.inspection_id, include_v2=True)]
        if analyst
        else [],
        "media_access": "Analyst-only recordings and their transcripts are omitted for judges",
    }

    # Normalize through Pydantic's own serializers for Decimal/datetime/enum values.
    def normalize(value):
        if hasattr(value, "model_dump"):
            return normalize(value.model_dump(mode="json"))
        if isinstance(value, dict):
            if not analyst and value.get("segment_id") in hidden_segments:
                return {
                    **{k: normalize(v) for k, v in value.items() if k != "quote"},
                    "quote": "Restricted source; analyst access required",
                }
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return normalize(result)


def text_report(snapshot):
    case = snapshot["case"]
    lines = [
        "Capital Deployment Integrity V2",
        f"Case: {case['company']} / {case['site']}",
        "SYNTHETIC DEMO - not real company evidence",
        snapshot["scope"],
        "",
        "Original V1 findings:",
    ]
    for visit in snapshot["v1_inspections"]:
        claims = {c["id"]: c for c in visit["claims"]}
        assets = {a["id"]: a for a in visit["assets"]}
        lines.append(
            f"Inspection: {visit['inspection']['name']} (current reconciliation: {visit['reconciliation_current']})"
        )
        for finding in visit["findings"]:
            claim = claims[finding["claim_id"]]
            lines.append(
                f"  {assets[claim['asset_id']]['tag']} / {claim['kind']}: computed={finding['computed_status']}; reviewed={finding['reviewed_status'] or 'pending'}"
            )
    lines += ["", "Investment Memory:"]
    for project in snapshot["investments"]:
        lines += [
            f"{project['title']} [{project['kind']}; {project['stage']}]",
            f"Rationale reported: {project['rationale']}",
            f"Proposed amount: {project['proposed_amount'] if project['proposed_amount'] is not None else 'unknown'} {project['currency'] or ''}",
            "Proposal is not proof of spending or payment.",
        ]
        for target in snapshot["targets"]:
            if target["project_id"] == project["id"]:
                lines.append(
                    f"  Forecast: {target['metric']} {target['target_type']} {target['target_value']} {target['unit']}; baseline={target['baseline_value'] if target['baseline_value'] is not None else 'unknown'}"
                )
                reviews = [r for r in snapshot["investment_reviews"] if r["target_id"] == target["id"]]
                lines.append(f"  Outcome: {reviews[-1]['status'] if reviews else 'not_yet_measurable'}")
                if reviews:
                    lines.append(
                        "  Calculation: " + json.dumps(reviews[-1]["calculation"], ensure_ascii=False)
                    )
        source = project["source"]
        lines.append(
            f"Source: {source['attribution']}; segment={source.get('segment_id') or 'manual/document'}; {source['quote']}"
        )
    lines += ["", "Deployment Closure:"]
    for item in snapshot["follow_ups"]:
        task, details = item["task"], item["details"]
        lines += [
            f"{details['workflow_status']}: {task['request']}",
            f"  Due: {details['due_date']}; contact: {details['contact']}; reviewer: {details['reviewer']}",
            "  Required verification: " + details["required_evidence"],
        ]
    lines += ["", "Machine Acoustic Memory:"]
    for audio in snapshot["audio"]:
        lines.append(
            f"{audio['id']} / asset {audio['physical_asset_id']} / {audio['duration_seconds']} seconds / SHA-256 {audio['sha256']}"
        )
        lines.append("  " + audio["note"] + "; conditions: " + audio["operating_mode"])
    for comparison in snapshot["comparisons"]:
        lines.append("Comparison: " + comparison["conclusion"])
    lines += ["", "Interview sources:"]
    for segment in snapshot["segments"]:
        lines += [
            f"Segment {segment['id']} revision {segment['version']} ({segment['mode']})",
            segment["text"],
        ]
        if segment["english_translation"]:
            lines.append(
                "English rendering ("
                + str(segment["translation_origin"])
                + "): "
                + segment["english_translation"]
            )
    lines += [
        "",
        "Recording/transcript locators require application authentication.",
        "Review completion, task closure, reported claims and independently supported evidence are distinct.",
    ]
    return "\n".join(lines) + "\n"


def pdf_report(snapshot, base_url):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="BodyCJK", fontName="HeiseiMin-W3", fontSize=9, leading=14, wordWrap="CJK", spaceAfter=6
        )
    )
    styles.add(
        ParagraphStyle(
            name="MetaV2",
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#58665c"),
            spaceAfter=6,
        )
    )
    styles["BodyText"].fontSize, styles["BodyText"].leading = 9, 14
    styles["Heading1"].textColor = colors.HexColor("#234d3c")
    styles["Heading2"].fontSize, styles["Heading2"].spaceBefore = 12, 12
    stream = io.BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=42,
        leftMargin=42,
        topMargin=45,
        bottomMargin=42,
        title="Capital Deployment Integrity V2 Review",
        author="Capital Deployment Integrity",
    )
    story = []

    def p(text, style="BodyText"):
        text = str(text).replace("\u2011", "-")
        chosen = (
            styles["BodyCJK"]
            if any(ord(char) > 255 for char in text) and style == "BodyText"
            else styles[style]
        )
        story.append(Paragraph(escape(text).replace("\n", "<br/>"), chosen))

    def source_link(segment_id, label="Open original source"):
        url = base_url.rstrip("/") + f"/api/v1/cases/{snapshot['case']['id']}/segments/{segment_id}"
        story.append(
            Paragraph(f'<link href="{escape(url)}" color="#245d43">{escape(label)}</link>', styles["MetaV2"])
        )

    p("Capital Deployment Integrity V2", "Title")
    p(snapshot["case"]["company"] + " / " + snapshot["case"]["site"], "Heading1")
    p("SYNTHETIC DEMO | Generated " + snapshot["generated_at"], "MetaV2")
    p(snapshot["scope"])
    p("Original inspection findings", "Heading2")
    for visit in snapshot["v1_inspections"]:
        p(visit["inspection"]["name"])
        if not visit["reconciliation_current"]:
            p("Reconciliation is stale or unavailable. Recompute before reviewing support.")
        claims = {c["id"]: c for c in visit["claims"]}
        rows = [["Machine", "Claim", "Computed", "Reviewed"]]
        assets = {a["id"]: a for a in visit["assets"]}
        for finding in visit["findings"]:
            claim = claims[finding["claim_id"]]
            values = [
                assets[claim["asset_id"]]["tag"],
                claim["kind"],
                finding["computed_status"],
                finding["reviewed_status"] or "pending",
            ]
            rows.append([Paragraph(escape(str(value)), styles["MetaV2"]) for value in values])
        table = Table(rows, colWidths=[85, 100, 165, 160], repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5eee8")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#9eafa3")),
                ]
            )
        )
        story += [table, Spacer(1, 8)]
    p("Investment Memory", "Heading2")
    if not snapshot["investments"]:
        p("No investment project has been recorded.")
    for project in snapshot["investments"]:
        p(project["title"])
        p(
            f"Type: {project['kind']}; workflow: {project['stage']}; proposed amount: {project['proposed_amount'] or 'unknown'} {project['currency'] or ''}."
        )
        p("Reported rationale: " + project["rationale"])
        p("A proposal is not evidence of actual spending, commissioning or realised benefit.", "MetaV2")
        for target in snapshot["targets"]:
            if target["project_id"] != project["id"]:
                continue
            p(
                f"Management forecast: {target['metric']}, {target['target_type']} {target['target_value']} {target['unit']}. Baseline: {target['baseline_value'] if target['baseline_value'] is not None else 'unknown'}."
            )
            reviews = [r for r in snapshot["investment_reviews"] if r["target_id"] == target["id"]]
            p("Outcome: " + (reviews[-1]["status"] if reviews else "not yet measurable"))
            if reviews:
                p("Calculation: " + json.dumps(reviews[-1]["calculation"]))
            if target["source"].get("segment_id"):
                source_link(target["source"]["segment_id"], "Original forecast source (authenticated)")
        if project["source"].get("segment_id"):
            source_link(project["source"]["segment_id"], "Original rationale source (authenticated)")
    p("Deployment Closure", "Heading2")
    if not snapshot["follow_ups"]:
        p("No enhanced follow-up has been recorded.")
    for item in snapshot["follow_ups"]:
        task, details = item["task"], item["details"]
        p(task["request"])
        p(
            f"Status: {details['workflow_status']}; due: {details['due_date']}; contact: {details['contact']}; reviewer: {details['reviewer']}.",
            "MetaV2",
        )
        p("Required verification: " + details["required_evidence"])
    p("Machine Acoustic Memory", "Heading2")
    if not snapshot["audio"]:
        p("No recording is available for your access level.")
    for audio in snapshot["audio"]:
        p(
            f"{audio['capture_type']}: {audio['duration_seconds']} seconds; operating mode: {audio['operating_mode']}."
        )
        p(audio["note"])
        p("Original SHA-256: " + audio["sha256"], "MetaV2")
        url = base_url.rstrip("/") + f"/api/v1/cases/{snapshot['case']['id']}/audio/{audio['id']}/original"
        story.append(
            Paragraph(
                f'<link href="{escape(url)}" color="#245d43">Play protected original (authentication required)</link>',
                styles["MetaV2"],
            )
        )
    for comparison in snapshot["comparisons"]:
        p(comparison["conclusion"])
    p("Interview source record", "Heading2")
    for segment in snapshot["segments"]:
        p(f"Source {segment['id']}; revision {segment['version']}; capture: {segment['mode']}.", "MetaV2")
        p(segment["text"])
        if segment["english_translation"]:
            p(
                "English rendering ("
                + str(segment["translation_origin"])
                + "): "
                + segment["english_translation"]
            )
        source_link(segment["id"])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#58665c"))
        canvas.drawString(42, 24, "Synthetic inspection review | Source access remains protected")
        canvas.drawRightString(A4[0] - 42, 24, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


def install_reporting(router, app, service, authenticate, get_report):
    store = service.store

    @router.get("/cases/{case_id}/export")
    def export(case_id: str, request: Request):
        with store.transaction(write=False) as db:
            return make_snapshot(service, db, request, case_id, get_report)

    @router.get("/cases/{case_id}/report", response_class=PlainTextResponse)
    def report(case_id: str, request: Request):
        with store.transaction(write=False) as db:
            snapshot = make_snapshot(service, db, request, case_id, get_report)
        return text_report(snapshot)

    @router.get("/cases/{case_id}/report.pdf")
    def report_pdf(case_id: str, request: Request):
        with store.transaction(write=False) as db:
            snapshot = make_snapshot(service, db, request, case_id, get_report)
        return Response(
            pdf_report(snapshot, str(request.base_url)),
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="capital-integrity-v2-review.pdf"',
                "Cache-Control": "no-store",
            },
        )

    @router.get("/inspections/{inspection_id}/v2-context")
    def inspection_context(inspection_id: str, request: Request, asset_id: str | None = None):
        with store.transaction(write=False) as db:
            case_id = service.case_for_visit(db, inspection_id)
            snapshot = make_snapshot(service, db, request, case_id, get_report)
            if not asset_id:
                return snapshot
            store.get(db, Asset, asset_id, inspection_id)
            bindings = [
                b for b in snapshot["asset_bindings"] if b["active"] and b["local_asset_id"] == asset_id
            ]
            if not bindings:
                return {
                    "case": snapshot["case"],
                    "identity_confirmed": False,
                    "history": [],
                    "next_action": "Confirm physical machine identity before V2 capture",
                }
            physical_id = bindings[0]["physical_asset_id"]
            projects = [
                p
                for p in snapshot["investments"]
                if any(a["physical_asset_id"] == physical_id for a in p["asset_links"])
            ]
            project_ids = {p["id"] for p in projects}
            interview_ids = {i["id"] for i in snapshot["interviews"] if i["physical_asset_id"] == physical_id}
            return {
                "case": snapshot["case"],
                "identity_confirmed": True,
                "physical_asset_id": physical_id,
                "bindings": [b for b in snapshot["asset_bindings"] if b["physical_asset_id"] == physical_id],
                "investments": projects,
                "targets": [t for t in snapshot["targets"] if t["project_id"] in project_ids],
                "investment_reviews": [
                    r for r in snapshot["investment_reviews"] if r["project_id"] in project_ids
                ],
                "follow_ups": [
                    f for f in snapshot["follow_ups"] if f["details"]["physical_asset_id"] == physical_id
                ],
                "audio": [a for a in snapshot["audio"] if a["physical_asset_id"] == physical_id],
                "segments": [s for s in snapshot["segments"] if s["interview_id"] in interview_ids],
                "statements": [s for s in snapshot["statements"] if s["physical_asset_id"] == physical_id],
                "analyses": [
                    a
                    for a in snapshot["analyses"]
                    if a["segment_id"]
                    in {s["id"] for s in snapshot["segments"] if s["interview_id"] in interview_ids}
                ],
            }
