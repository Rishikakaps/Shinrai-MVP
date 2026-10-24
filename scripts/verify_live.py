"""Start a real Uvicorn process, seed via HTTP, stop, restart, and verify persisted evidence."""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.models import now
from scripts.demo import PREFIX, ok, seed


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    root = Path(__file__).resolve().parents[1]
    output = root / "output"
    output.mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    analyst = os.environ["CDI_ANALYST_TOKEN"]
    judge = os.environ["CDI_JUDGE_TOKEN"]
    process = None
    with (output / "live-startup.log").open("w") as log:

        def start():
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Server exited; inspect output/live-startup.log")
                try:
                    if httpx.get(url + "/health", timeout=0.5).status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError("Server startup timed out")

        def stop(process):
            process.terminate()
            process.wait(timeout=15)
            assert process.returncode in ((0, 1) if os.name == "nt" else (0, -signal.SIGTERM))

        try:
            process = start()
            with httpx.Client(
                base_url=url, headers={"Authorization": "Bearer " + analyst}, timeout=90
            ) as client:
                snapshot = seed(client)
                iid = snapshot["inspection"]["id"]
                path = f"{PREFIX}/inspections/{iid}"
                assert (
                    snapshot["reconciliation_current"]
                    and snapshot["inspection"]["state"] == "review_complete"
                )
                assert httpx.get(url + path + "/export").status_code == 401
                with httpx.Client(base_url=url, headers={"Authorization": "Bearer " + judge}) as reader:
                    assert reader.get(path + "/export").status_code == 200
                    assert (
                        reader.post(path + "/reconcile", json={"reason": "Cannot write"}).status_code == 403
                    )
                action = snapshot["follow_ups"][0]
                for state in ("resolved", "open"):
                    action = ok(
                        client.patch(
                            path + f"/follow-ups/{action['id']}",
                            json={
                                "version": action["version"],
                                "state": state,
                                "resolution": "Synthetic HTTP verification",
                                "reason": "Exercise follow-up lifecycle",
                            },
                        )
                    )
                snapshot = ok(client.get(path + "/export"))
                (output / "plant-a-report.txt").write_text(client.get(path + "/report").text)
                (root / "docs" / "openapi.json").write_text(
                    json.dumps(ok(client.get("/openapi.json")), indent=2)
                )
                (output / "plant-a-export.json").write_text(json.dumps(snapshot, indent=2))
            stop(process)
            process = start()
            with httpx.Client(
                base_url=url, headers={"Authorization": "Bearer " + judge}, timeout=30
            ) as client:
                restored = ok(client.get(path + "/export"))
                for field in (
                    "inspection",
                    "claims",
                    "evidence",
                    "evidence_links",
                    "findings",
                    "review_events",
                    "follow_ups",
                ):
                    assert restored[field] == snapshot[field], field
                for ev in restored["evidence"]:
                    content = client.get(path + f"/evidence/{ev['id']}/original")
                    assert content.status_code == 200
                    assert hashlib.sha256(content.content).hexdigest() == ev["sha256"]
            result = {
                "verified_at": now(),
                "transport": "Actual loopback HTTP against Uvicorn",
                "startup": "passed",
                "process_restart": "passed",
                "role_checks": "passed",
                "inspection_id": iid,
                "assets": len(snapshot["assets"]),
                "claims": len(snapshot["claims"]),
                "originals_verified_after_restart": len(snapshot["evidence"]),
                "immutable_events_preserved": len(snapshot["review_events"]),
                "computed_status_counts": {
                    status: sum(f["computed_status"] == status for f in snapshot["findings"])
                    for status in ("supported", "unresolved")
                },
                "limitations": [
                    "Source six-page product PDF unavailable",
                    "Docker daemon unavailable; container not executed",
                ],
            }
            (output / "verification.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
        finally:
            if process and process.poll() is None:
                stop(process)


if __name__ == "__main__":
    main()
