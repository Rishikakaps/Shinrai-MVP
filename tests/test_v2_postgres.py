"""Reuse important V2 workflows against actual PostgreSQL, never an in-memory imitation."""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests import test_v2_backend as flows
from tests.conftest import ANALYST, TOKENS

v2 = flows.v2

pytestmark = pytest.mark.skipif(
    not os.environ.get("CDI_TEST_DATABASE_URL"), reason="Isolated PostgreSQL test database not configured"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CDI_AUTO_MIGRATE", "true")
    with TestClient(
        create_app(tmp_path, TOKENS, database_url=os.environ["CDI_TEST_DATABASE_URL"]),
        headers={"Authorization": "Bearer " + ANALYST},
    ) as client:
        yield client


def test_postgres_audio(v2):
    flows.test_audio_bytes_hash_range_playback_and_retry(v2)


def test_postgres_case_isolation(v2):
    flows.test_case_membership_cannot_be_guessed_or_moved(v2)


def test_postgres_strict_closure(v2):
    flows.test_closure_requires_underlying_supported_review_and_old_route_cannot_bypass(v2)


def test_postgres_candidate_confirmation(v2, monkeypatch):
    flows.test_copilot_mocked_contract_confirmation_edit_audit_and_no_claim_promotion(v2, monkeypatch)


def test_postgres_project_audit(v2):
    flows.test_project_retry_revision_and_audit(v2)


def test_postgres_preserves_v1_basis(v2):
    flows.test_v2_identity_preserves_original_finding_basis(v2)
