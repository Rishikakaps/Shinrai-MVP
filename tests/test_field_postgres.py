"""Same field flows on an explicitly isolated PostgreSQL test database."""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests import test_field_workflow as flows
from tests.conftest import ANALYST, TOKENS

field = flows.field
pytestmark = pytest.mark.skipif(
    not os.environ.get("CDI_TEST_DATABASE_URL"), reason="Isolated PostgreSQL test database not configured"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["CDI_TEST_DATABASE_URL"])
    monkeypatch.setenv("CDI_AUTO_MIGRATE", "true")
    with TestClient(create_app(tmp_path, TOKENS), headers={"Authorization": "Bearer " + ANALYST}) as client:
        yield client


def test_postgres_capture_binding_and_restart(field):
    flows.test_real_capture_review_binding_retry_restart_and_retrieval(field)


def test_postgres_documentary_review(field):
    flows.test_documentary_quantity_does_not_create_physical_identities(field)


def test_postgres_source_conflict_review(field):
    flows.test_conflict_requires_explicit_resolution_and_raw_is_immutable(field)
