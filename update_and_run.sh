#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo"
VENV_DIR="$APP_DIR/.venv"

echo "==== 1. Pulling latest code from git ===="
git -C "$ROOT_DIR" pull --ff-only origin main

echo "==== 2. Preparing Python environment ===="
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    if command -v python3.11 >/dev/null 2>&1; then
        python3.11 -m venv "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

echo "==== 3. Ensuring config.toml exists ===="
if [[ ! -f "$APP_DIR/config.toml" ]]; then
    cp "$APP_DIR/config.example.toml" "$APP_DIR/config.toml"
    echo "Created $APP_DIR/config.toml from config.example.toml"
    echo "Edit config.toml with API keys before running real uploads."
fi

echo "==== 4. Running auto publish script ===="
"$ROOT_DIR/run_daily_auto_publish.sh" "$@"

echo "==== Done ===="
