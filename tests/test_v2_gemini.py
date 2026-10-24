"""Verify Google's REST contract and fail-closed provider handling."""

import base64
import json

import httpx
import pytest
from fastapi import HTTPException

from app.v2_providers import GeminiProvider


def mock_google(monkeypatch, text, status=200, finish="STOP"):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    captured = []
    original = httpx.Client

    def handle(request):
        captured.append(request)
        return httpx.Response(
            status, json={"candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}]}
        )

    monkeypatch.setattr(
        "app.v2_providers.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    return GeminiProvider(), captured


def test_google_analysis_header_schema_and_source_validation(monkeypatch):
    provider, requests = mock_google(monkeypatch, '{"questions": [], "candidates": []}')
    assert provider.analyse("Reported downtime", {}).candidates == []
    request = requests[0]
    assert (
        str(request.url)
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    )
    assert request.headers["x-goog-api-key"] == "test-only-key"
    assert "test-only-key" not in str(request.url)
    config = json.loads(request.content)["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "low"}
    assert config["responseMimeType"] == "application/json"
    assert "questions" in config["responseJsonSchema"]["properties"]
    assert "$ref" not in json.dumps(config["responseJsonSchema"])


def test_japanese_audio_retains_original_bytes_and_translation(monkeypatch, tmp_path):
    path = tmp_path / "original"
    path.write_bytes(b"validated-fixture")
    provider, requests = mock_google(
        monkeypatch,
        json.dumps({"text": "約三百万円です。", "english_translation": "Approximately three million yen."}),
    )
    text, translation = provider.transcribe(path, "clip.m4a", "audio/mp4", "ja")
    assert text == "約三百万円です。" and "Approximately" in translation
    audio = json.loads(requests[0].content)["contents"][0]["parts"][1]["inlineData"]
    assert audio["mimeType"] == "audio/m4a"
    assert base64.b64decode(audio["data"]) == path.read_bytes()


@pytest.mark.parametrize("status,expected", [(429, 429), (403, 503), (404, 503), (500, 502)])
def test_google_errors_do_not_expose_secrets(monkeypatch, status, expected):
    provider, _ = mock_google(monkeypatch, "secret provider details", status)
    with pytest.raises(HTTPException) as caught:
        provider.translate("試験")
    assert caught.value.status_code == expected
    assert "secret" not in caught.value.detail and "test-only-key" not in caught.value.detail


@pytest.mark.parametrize("error,expected", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 503)])
def test_network_failure_is_retryable_and_does_not_expose_request(monkeypatch, error, expected):
    monkeypatch.setenv("GEMINI_API_KEY", "private-test-key")
    original = httpx.Client

    def fail(request):
        raise error("private upstream diagnostic", request=request)

    monkeypatch.setattr(
        "app.v2_providers.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(fail), **kwargs),
    )
    with pytest.raises(HTTPException) as caught:
        GeminiProvider().translate("試験")
    assert caught.value.status_code == expected
    assert "saved sources are retained" in caught.value.detail
    assert "private" not in caught.value.detail


@pytest.mark.parametrize("text,finish", [("", "STOP"), ("partial", "MAX_TOKENS"), ("blocked", "SAFETY")])
def test_partial_blocked_empty_generations_fail(monkeypatch, text, finish):
    provider, _ = mock_google(monkeypatch, text, finish=finish)
    with pytest.raises(HTTPException) as caught:
        provider.translate("試験")
    assert caught.value.status_code == 502


def test_key_alias_and_no_model_url(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "alias-test-key")
    assert GeminiProvider.key() == "alias-test-key"
    monkeypatch.delenv("GOOGLE_API_KEY")
    assert not GeminiProvider.configured()
    with pytest.raises(HTTPException):
        GeminiProvider.key()
    monkeypatch.setenv("GEMINI_MODEL", "https://example.test/steal")
    with pytest.raises(ValueError):
        GeminiProvider()


def test_invented_source_quote_is_rejected(monkeypatch):
    provider, _ = mock_google(
        monkeypatch,
        json.dumps(
            {
                "questions": [
                    {
                        "topic": "maintenance",
                        "question": "Show records?",
                        "why": "Clarify",
                        "proposed_evidence": "Service records",
                        "priority": "high",
                        "source_quote": "invented quote",
                    }
                ],
                "candidates": [],
            }
        ),
    )
    with pytest.raises(HTTPException) as caught:
        provider.analyse("Actual source words", {})
    assert caught.value.status_code == 502


def test_japanese_without_translation_is_not_partial_success(monkeypatch, tmp_path):
    path = tmp_path / "original"
    path.write_bytes(b"validated-fixture")
    provider, _ = mock_google(monkeypatch, '{"text": "試験", "english_translation": null}')
    with pytest.raises(HTTPException) as caught:
        provider.transcribe(path, "clip.wav", "audio/wav", "ja")
    assert caught.value.status_code == 502
    assert path.read_bytes() == b"validated-fixture"
