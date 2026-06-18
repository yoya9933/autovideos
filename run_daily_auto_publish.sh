#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTABLE_DIR="$ROOT_DIR/MoneyPrinterTurbo-Portable-Windows-1.2.6"
APP_DIR="$PORTABLE_DIR/MoneyPrinterTurbo"
LOG_DIR="$APP_DIR/storage/auto_publish/logs"
BAT_COMPAT_LOG="$LOG_DIR/sh_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"
find "$LOG_DIR" -name 'sh_*.log' -type f -mtime +30 -delete 2>/dev/null || true

pick_python() {
    if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
        printf '%s\n' "$APP_DIR/.venv/bin/python"
        return 0
    fi
    if command -v python3.11 >/dev/null 2>&1; then
        command -v python3.11
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    return 1
}

PYTHON_EXE="${PYTHON_EXE:-$(pick_python || true)}"
if [[ -z "$PYTHON_EXE" ]]; then
    echo "Python 3.11/python3 not found. Create .venv or install python3.11." >&2
    exit 127
fi

if command -v ffmpeg >/dev/null 2>&1; then
    export FFMPEG_BINARY="${FFMPEG_BINARY:-$(command -v ffmpeg)}"
    export IMAGEIO_FFMPEG_EXE="${IMAGEIO_FFMPEG_EXE:-$FFMPEG_BINARY}"
fi

if command -v magick >/dev/null 2>&1; then
    export IMAGEMAGICK_BINARY="${IMAGEMAGICK_BINARY:-$(command -v magick)}"
elif command -v convert >/dev/null 2>&1; then
    export IMAGEMAGICK_BINARY="${IMAGEMAGICK_BINARY:-$(command -v convert)}"
fi

cd "$APP_DIR" || exit 1
echo "Logging to: $BAT_COMPAT_LOG"

{
    echo "==== $(date '+%F %T') run_daily_auto_publish start ===="
    "$PYTHON_EXE" auto_publish_youtube.py "$@"
    exit_code=$?
    echo "==== $(date '+%F %T') run_daily_auto_publish exit $exit_code ===="
    exit "$exit_code"
} >> "$BAT_COMPAT_LOG" 2>&1
