# Backend and app deployment

The browser app and API are served by the same FastAPI process. No Node server, frontend build step, separate frontend origin or vision API is required.

## Local trial (SQLite)

Use Python 3.12+ and install `requirements.lock`. Install Tesseract and Poppler for OCR and PDF previews (`brew install tesseract poppler` on macOS; `apt-get install tesseract-ocr poppler-utils` on Linux). On Windows, install trusted distributions of these tools and add their executable directories to PATH; `.tools/tesseract/tesseract.exe` is also recognized by the runner.

```sh
python -m scripts.configure
python -m scripts.serve
```

Run with the repository virtual environment's Python. Open `http://127.0.0.1:8000/app`. The configuration script creates `.env` once and keeps existing credentials. Use its `CDI_ANALYST_TOKEN` or `CDI_JUDGE_TOKEN` value in the access-key form. There are no committed usable deployment credentials. Judge access is read-only, including direct API calls.

`PORT` changes the listener port; `CDI_HOST` defaults to `127.0.0.1`. `CDI_ENV_FILE` optionally selects another private environment file (relative paths resolve from the repository). Existing process environment settings take precedence over file settings.

SQLite persists in `CDI_DATA_DIR/integrity.sqlite3`; originals persist in `CDI_DATA_DIR/files`. Keep both. Browser sessions also survive process restarts but expire after 12 hours and are invalidated when their configured access key is removed. Local trial data and credentials must not be committed.

## Supabase / Postgres option from the uploaded backend

Keep the generated `CDI_TOKENS` configuration and add these settings privately:

```dotenv
DATABASE_URL=your-private-postgres-session-pooler-connection-string
CDI_AUTO_MIGRATE=true
CDI_REQUIRE_POSTGRES=true
CDI_DB_POOL_SIZE=4
CDI_DATA_DIR=data
```

Use the exact Session pooler connection details from the database owner. Supabase connections require encrypted transport. The application creates a private `cdi` schema with JSONB entities, immutable review-event triggers and browser sessions. Run `python -m scripts.migrate` explicitly when automatic migration is disabled. Migration requires an account allowed to create this schema and its objects. The POC uses one advisory writer lock to preserve transaction ordering; read-only requests use independent snapshots.

Postgres does **not** move the original evidence into hosted object storage: the app's `files/` directory still needs persistent local storage. This release does not migrate existing SQLite data into Postgres. Selecting a new database begins with that database's records.

`compose.yaml` follows the uploaded Postgres deployment setup and requires `DATABASE_URL`; it does not silently fall back to SQLite. The native runner remains the minimal SQLite option. Docker stores original files in the named `evidence-data` volume. Do not remove that volume when recreating the service.

```sh
docker compose up -d --build
```

The container is non-root, has a read-only app filesystem, resource limits and a `/ready` health check. The local Docker daemon was unavailable during native verification; GitHub Actions builds the image. A Docker build is not evidence of a running hosted deployment.

## Controlled HTTPS access

The ZIP includes an optional ngrok runner (`python -m scripts.tunnel`) and Compose tunnel profile. Both need a private `NGROK_AUTHTOKEN`; optional `NGROK_URL` selects an assigned endpoint. No tunnel is started automatically. Authentication stays enabled. Set `CDI_COOKIE_SECURE=true` for HTTPS deployments and configure trusted proxy forwarding correctly so the app sees the external HTTPS origin. Validate this through the intended proxy before inviting judges. Never copy the local QA keys into a shared deployment.

The uploaded tunnel configuration and a real Supabase account were not exercised. Local SQLite and a real isolated Postgres 16 server were tested. External HTTPS access and testing from the other laptops remain deployment acceptance work.

## Health, backup and restore

`/health` reports process liveness; `/ready` checks the database, writable originals storage and optionally Tesseract (`CDI_REQUIRE_OCR=true`). These routes reveal no credentials. Authenticated `/api/v1/meta` describes storage and extraction capabilities.

For SQLite, set `CDI_DATA_DIR` and run `python -m scripts.backup /new/backup/path`. The script refuses missing/corrupt originals and verifies copied digests. Stop the service before restoring the backup directory; retain private configuration separately. Postgres requires database-native backup plus a coordinated originals snapshot; this script refuses to label a SQLite backup as a Postgres backup.
