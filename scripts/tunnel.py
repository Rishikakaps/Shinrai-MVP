"""Publish the already-running backend through ngrok; credentials stay in .env."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pyngrok import conf, ngrok
from pyngrok.exception import PyngrokError


def endpoint_options(port, endpoint=""):
    """Use the v3 endpoint schema; legacy bind_tls becomes an invalid schemes field."""
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    options = {"upstream": {"url": f"http://127.0.0.1:{port}"}, "bindings": ["public"]}
    if endpoint:
        parsed = urlparse(endpoint if "://" in endpoint else "https://" + endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("NGROK_URL must be an HTTPS endpoint hostname without credentials or a path")
        options["url"] = "https://" + parsed.netloc
    return options


def main():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)
    token = os.environ.get("NGROK_AUTHTOKEN", "").strip()
    if not token:
        raise SystemExit("Set NGROK_AUTHTOKEN in the private .env before starting the tunnel")
    tools = root / ".tools"
    tools.mkdir(exist_ok=True)
    config = conf.PyngrokConfig(
        ngrok_path=str(tools / ("ngrok.exe" if os.name == "nt" else "ngrok")),
        config_path=str(tools / "ngrok.yml"),
        auth_token=token,
        monitor_thread=True,
        config_version="3",
    )
    try:
        options = endpoint_options(os.environ.get("PORT", "8000"), os.environ.get("NGROK_URL", "").strip())
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    try:
        tunnel = ngrok.connect(pyngrok_config=config, **options)
        if urlparse(tunnel.public_url).scheme != "https":
            raise SystemExit("ngrok did not create the required HTTPS endpoint")
        print("Backend HTTPS endpoint:", tunnel.public_url, flush=True)
        print("Health:", tunnel.public_url + "/health", flush=True)
        ngrok.get_ngrok_process(pyngrok_config=config).proc.wait()
    except KeyboardInterrupt:
        pass
    except PyngrokError:
        raise SystemExit("ngrok could not start. Check the private token, account endpoint and network.")
    finally:
        ngrok.kill(pyngrok_config=config)


if __name__ == "__main__":
    main()
