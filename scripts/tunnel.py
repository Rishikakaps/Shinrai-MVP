"""Publish the already-running backend through ngrok; credentials stay in .env."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pyngrok import conf, ngrok
from pyngrok.exception import PyngrokError


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
    )
    options = {"bind_tls": True}
    endpoint = os.environ.get("NGROK_URL", "").strip()
    if endpoint:
        options["domain"] = urlparse(endpoint if "://" in endpoint else "https://" + endpoint).netloc
    try:
        tunnel = ngrok.connect(
            addr="127.0.0.1:" + os.environ.get("PORT", "8000"), proto="http", pyngrok_config=config, **options
        )
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
