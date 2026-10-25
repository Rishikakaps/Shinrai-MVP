"""Guard the actual v3 agent contract; no cloud account or credentials are used."""

from types import SimpleNamespace

import pytest
from pyngrok.exception import PyngrokError

from scripts import tunnel


@pytest.mark.parametrize(
    "endpoint", ["", "tablet-example.ngrok-free.app", "https://tablet-example.ngrok-free.app/"]
)
def test_launcher_uses_v3_endpoint_schema_and_private_credentials(monkeypatch, capsys, endpoint):
    monkeypatch.setenv("NGROK_AUTHTOKEN", "synthetic-secret-not-a-real-token")
    monkeypatch.setenv("NGROK_URL", endpoint)
    monkeypatch.setenv("PORT", "8004")
    monkeypatch.setattr(tunnel, "load_dotenv", lambda *args, **kwargs: None)
    calls, killed = [], []

    def connect(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(public_url="https://tablet-example.ngrok-free.app")

    monkeypatch.setattr(tunnel.ngrok, "connect", connect)
    monkeypatch.setattr(
        tunnel.ngrok,
        "get_ngrok_process",
        lambda **kwargs: SimpleNamespace(proc=SimpleNamespace(wait=lambda: None)),
    )
    monkeypatch.setattr(tunnel.ngrok, "kill", lambda **kwargs: killed.append(kwargs))
    tunnel.main()
    args = calls[0]
    assert args["pyngrok_config"].config_version == "3"
    assert args["upstream"] == {"url": "http://127.0.0.1:8004"}
    assert args["bindings"] == ["public"]
    assert not {"bind_tls", "schemes", "addr", "proto", "domain"}.intersection(args)
    assert (args.get("url") == "https://tablet-example.ngrok-free.app") if endpoint else ("url" not in args)
    assert len(killed) == 1
    assert "synthetic-secret-not-a-real-token" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test",
        "https://user:secret@example.test",
        "https://example.test/path",
        "https://example.test?key=value",
    ],
)
def test_endpoint_refuses_insecure_or_credential_urls(endpoint):
    with pytest.raises(ValueError):
        tunnel.endpoint_options(8004, endpoint)


def test_launcher_failure_cleans_its_agent_without_echoing_credentials(monkeypatch):
    monkeypatch.setenv("NGROK_AUTHTOKEN", "synthetic-private-token")
    monkeypatch.setenv("NGROK_URL", "")
    monkeypatch.setenv("PORT", "8004")
    monkeypatch.setattr(tunnel, "load_dotenv", lambda *args, **kwargs: None)
    killed = []

    def fail(**kwargs):
        raise PyngrokError("Provider diagnostic containing synthetic-private-token")

    monkeypatch.setattr(tunnel.ngrok, "connect", fail)
    monkeypatch.setattr(tunnel.ngrok, "kill", lambda **kwargs: killed.append(kwargs))
    with pytest.raises(SystemExit) as error:
        tunnel.main()
    assert "synthetic-private-token" not in str(error.value)
    assert len(killed) == 1
