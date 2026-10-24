"""Persisted due-date outbox delivering only to the authorized local test inbox."""

import hashlib
import os
import smtplib
import sqlite3
import threading
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from psycopg import Error as PostgresError

from app.models import FollowUpAction, now
from app.v2_models import CaseRecord, FollowUpContext, ReminderDelivery, ReminderRun


class ReminderScheduler:
    def __init__(self, service):
        self.service = service
        self.stop_event = threading.Event()
        self.thread = None
        self.last_error = None

    def start(self):
        if os.environ.get("CDI_ENABLE_REMINDERS", "").lower() not in {"true", "1"}:
            return
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.loop, name="cdi-test-reminders", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=6)

    def loop(self):
        while not self.stop_event.is_set():
            try:
                with self.service.store.transaction(write=False) as db:
                    cases = self.service.store.list(db, CaseRecord)
                for case in cases:
                    if self.stop_event.is_set():
                        break
                    self.run(case.id, "System reminder scheduler", "Scheduled due-date check")
                self.last_error = None
            except (HTTPException, ValueError, OSError, sqlite3.Error, PostgresError):
                self.last_error = "Reminder check failed; inspect delivery states and local SMTP availability"
            self.stop_event.wait(30)

    def run(self, case_id, actor, reason, retry_failed=False):
        service, store = self.service, self.service.store
        if os.environ.get("CDI_EMAIL_MODE", "test") != "test":
            raise HTTPException(403, "This hackathon build only sends email to a local test inbox")
        host = os.environ.get("CDI_SMTP_HOST", "127.0.0.1")
        port = int(os.environ.get("CDI_SMTP_PORT", "11025"))
        recipient = os.environ.get("CDI_REMINDER_RECIPIENT", "analyst@example.test")
        if (
            host not in {"127.0.0.1", "localhost", "mailpit"}
            or not recipient.endswith(".test")
            or any(c in recipient for c in "\r\n ,;")
        ):
            raise HTTPException(
                422, "Configure a local Mailpit host and a .test recipient; real email delivery is disabled"
            )
        with store.transaction(write=False) as db:
            case = service.get_case(db, case_id)
            due = [item for item in service.due(db, case_id) if item["overdue"] or item["due_today"]]
        results = []
        for entry in due:
            context = entry["details"]
            raw_id = case_id + ":" + context.follow_up_id + ":" + context.due_date
            delivery_id = "reminder-" + hashlib.sha256(raw_id.encode()).hexdigest()
            with store.transaction() as db:
                current = service.get(db, FollowUpContext, context.id, case_id)
                if current.workflow_status == "closed" or current.due_date != context.due_date:
                    continue
                existing = next(
                    (d for d in service.list(db, ReminderDelivery, case_id) if d.id == delivery_id), None
                )
                if existing:
                    if existing.status == "sent_to_test_inbox":
                        results.append(existing)
                        continue
                    if (
                        existing.attempt_started_at
                        and (
                            datetime.now(UTC) - datetime.fromisoformat(existing.attempt_started_at)
                        ).total_seconds()
                        < 60
                    ):
                        results.append(existing)
                        continue
                    if existing.attempts >= 3 and not retry_failed:
                        results.append(existing)
                        continue
                    item = existing
                else:
                    item = ReminderDelivery(
                        id=delivery_id,
                        case_id=case_id,
                        inspection_id=context.inspection_id,
                        follow_up_id=context.follow_up_id,
                        due_date=context.due_date,
                        recipient=recipient,
                        status="pending",
                        message_id="<" + delivery_id + "@capital-integrity.test>",
                    )
                item.attempts += 1
                item.attempt_started_at = now()
                item.status, item.error = "pending", None
                service.save(db, item, actor, reason, "v2.reminder.delivery_attempted")
                task = store.get(db, FollowUpAction, context.follow_up_id)
            message = EmailMessage()
            message["From"], message["To"] = "inspector@capital-integrity.test", recipient
            message["Subject"] = "[TEST INBOX] Inspection evidence request due " + context.due_date
            message["Message-ID"], message["Date"] = item.message_id, format_datetime(datetime.now(UTC))
            message.set_content(
                "SYNTHETIC HACKATHON DEMO - LOCAL TEST INBOX ONLY\n\n"
                f"Case: {case.company} / {case.site}\nRequest: {task.request}\nDue: {context.due_date} ({case.timezone})\n"
                f"Reported contact: {context.contact}\nReviewer: {context.reviewer}\n"
                f"Required verification: {context.required_evidence}\nTask ID: {task.id}\n\n"
                "A missed date does not establish fraud or change an inspection finding."
            )
            status, error = "sent_to_test_inbox", None
            try:
                with smtplib.SMTP(host, port, timeout=5) as smtp:
                    smtp.send_message(message)
            except (OSError, smtplib.SMTPException):
                status, error = "failed", "Local test SMTP unavailable; no real recipient was contacted"
            with store.transaction() as db:
                fresh = service.get(db, ReminderDelivery, item.id, case_id)
                fresh.status, fresh.error = status, error
                service.save(db, fresh, actor, reason, "v2.reminder.delivery_completed")
                results.append(fresh)
        return results


def install_reminders(router, app, service, authenticate):
    Actor = Annotated[str, Depends(authenticate)]
    scheduler = ReminderScheduler(service)
    app.state.reminder_scheduler = scheduler

    @router.post("/cases/{case_id}/reminders/run", response_model=list[ReminderDelivery])
    def run_reminders(case_id: str, body: ReminderRun, actor: Actor):
        return scheduler.run(case_id, actor, body.reason, body.retry_failed)

    @router.get("/cases/{case_id}/reminders", response_model=list[ReminderDelivery])
    def deliveries(case_id: str, request: Request):
        if request.state.principal["role"] != "analyst":
            raise HTTPException(403, "Reminder delivery details are restricted to analysts")
        with service.store.transaction(write=False) as db:
            return service.list(db, ReminderDelivery, case_id)
