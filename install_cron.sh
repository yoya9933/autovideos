#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SCRIPT="$ROOT_DIR/run_daily_auto_publish.sh"
MARK_BEGIN="# VideoTurn auto publish begin"
MARK_END="# VideoTurn auto publish end"

if ! command -v crontab >/dev/null 2>&1; then
    echo "crontab command not found. Install cron first." >&2
    exit 127
fi

chmod +x "$RUN_SCRIPT"

current_cron="$(mktemp)"
new_cron="$(mktemp)"
trap 'rm -f "$current_cron" "$new_cron"' EXIT

crontab -l > "$current_cron" 2>/dev/null || true

awk -v begin="$MARK_BEGIN" -v end="$MARK_END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    !skip { print }
' "$current_cron" > "$new_cron"

cat >> "$new_cron" <<EOF
$MARK_BEGIN
0 12 * * * "$RUN_SCRIPT"
0 20 * * * "$RUN_SCRIPT"
$MARK_END
EOF

crontab "$new_cron"

echo "Installed VideoTurn cron jobs:"
echo "  12:00 daily -> $RUN_SCRIPT"
echo "  20:00 daily -> $RUN_SCRIPT"
