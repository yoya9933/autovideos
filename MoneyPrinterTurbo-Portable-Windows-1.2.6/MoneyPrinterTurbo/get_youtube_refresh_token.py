from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests


SCOPE = "https://www.googleapis.com/auth/youtube.upload"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _mask_secret(value: str, visible: int = 6) -> str:
    if len(value) <= visible * 2:
        return "***"
    return f"{value[:visible]}...{value[-visible:]}"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code: str = ""
    auth_error: str = ""

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        OAuthCallbackHandler.auth_code = query.get("code", [""])[0]
        OAuthCallbackHandler.auth_error = query.get("error", [""])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if OAuthCallbackHandler.auth_code:
            body = "<h1>Authorization complete</h1><p>You can return to the terminal.</p>"
        else:
            body = "<h1>Authorization failed</h1><p>You can return to the terminal.</p>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        return


def _default_client_secret_path() -> Path:
    root_dir = Path(__file__).resolve().parents[2]
    matches = sorted(root_dir.glob("client_secret_*.json"))
    if matches:
        return matches[0]
    return root_dir / "client_secret.json"


def _load_installed_client(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    client = payload.get("installed") or payload.get("web")
    if not client:
        raise ValueError("client secret JSON must contain an 'installed' or 'web' object")
    return client


def _exchange_code_for_tokens(client: dict, code: str, redirect_uri: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _replace_config_value(config_text: str, key: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    pattern = rf"^({re.escape(key)}\s*=\s*)\".*\""
    replacement = rf'\1"{escaped}"'
    updated, count = re.subn(pattern, replacement, config_text, flags=re.MULTILINE)
    if count:
        return updated
    return config_text.rstrip() + f'\n{key} = "{escaped}"\n'


def _write_config(config_path: Path, client: dict, refresh_token: str) -> None:
    config_text = config_path.read_text(encoding="utf-8")
    config_text = _replace_config_value(config_text, "youtube_client_id", client["client_id"])
    config_text = _replace_config_value(config_text, "youtube_client_secret", client["client_secret"])
    config_text = _replace_config_value(config_text, "youtube_refresh_token", refresh_token)
    config_text = _replace_config_value(config_text, "youtube_upload_privacy_status", "private")
    config_path.write_text(config_text, encoding="utf-8")


def _serve_once(server: HTTPServer) -> None:
    server.handle_request()


def run() -> int:
    parser = argparse.ArgumentParser(description="Get a YouTube upload refresh token for MoneyPrinterTurbo.")
    parser.add_argument("--client-secret", default=str(_default_client_secret_path()))
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.toml"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--write-config", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    client_secret_path = Path(args.client_secret).resolve()
    config_path = Path(args.config).resolve()
    client = _load_installed_client(client_secret_path)

    server = HTTPServer(("localhost", args.port), OAuthCallbackHandler)
    redirect_uri = f"http://localhost:{args.port}/"

    auth_params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
    }
    auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"

    thread = threading.Thread(target=_serve_once, args=(server,), daemon=True)
    thread.start()

    print("Open this URL and authorize YouTube upload access:")
    print(auth_url)
    print()
    if not args.no_browser:
        webbrowser.open(auth_url)

    deadline = time.time() + 300
    while time.time() < deadline and not OAuthCallbackHandler.auth_code and not OAuthCallbackHandler.auth_error:
        time.sleep(0.2)

    server.server_close()

    if OAuthCallbackHandler.auth_error:
        print(f"Authorization failed: {OAuthCallbackHandler.auth_error}", file=sys.stderr)
        return 1
    if not OAuthCallbackHandler.auth_code:
        print("Timed out waiting for browser authorization.", file=sys.stderr)
        return 1

    tokens = _exchange_code_for_tokens(client, OAuthCallbackHandler.auth_code, redirect_uri)
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        print("Google did not return a refresh_token. Revoke the old grant and try again.", file=sys.stderr)
        return 1

    print("New OAuth values:")
    print(f'youtube_client_id = "{client["client_id"]}"')
    print(f'youtube_client_secret = "{_mask_secret(client["client_secret"])}"')
    print(f'youtube_refresh_token = "{_mask_secret(refresh_token)}"')
    print('youtube_upload_privacy_status = "private"')

    if args.write_config:
        _write_config(config_path, client, refresh_token)
        print()
        print(f"Updated config: {config_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
