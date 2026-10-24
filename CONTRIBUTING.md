# Maintaining this project

## User-requested GitHub synchronization

The project owner requested on 24 October 2026 that every future codebase update also be updated on GitHub.

For changes made to this project:

1. Inspect local changes first and preserve unrelated work.
2. Make a focused change and run the relevant checks. For backend behavior, run the acceptance/failure tests; do not present a failing build as verified.
3. Update documentation when behavior, setup, API contracts or limitations change. Describe what works, what was verified and what remains unfinished.
4. Review the exact files being committed. Never commit `.env`, credentials, real sensitive evidence, local databases, runtime storage or synced ChatGPT reference material.
5. Commit the completed change with a meaningful subject and concise explanation; push it to this repository. Do not rewrite published history or force-push.
6. Report the commit/push result. If access or network problems block synchronization, preserve the local work and state that GitHub is not yet updated.

This is a workflow for completed changes, not a background watcher that uploads every file save. Keep runtime data and generated private configuration local. The initial `output/` examples contain explicitly synthetic verification evidence; do not replace them with real customer documents.

## Checks

Install `requirements.lock` and system Tesseract/Poppler, then run:

```sh
python -m pytest -q
python -m ruff check app scripts tests
python -m ruff format --check app scripts tests
```

GitHub Actions repeats these checks on pushes and pull requests. Tests use temporary storage and synthetic data; no real credentials or hosted service are needed.

## Current scope

Read `README.md`, `docs/requirements.md` and `docs/frontend-plan.md` before expanding the application. The backend is implemented; the frontend and shared remote deployment remain unfinished. The source six-page product PDF was unavailable at implementation time. The latest saved live exercise resolved CNC-002 commissioning and retained its earlier unresolved conclusion.
