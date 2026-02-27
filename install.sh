#!/bin/bash
# fatigue-monitor installer
# Installs a launchd agent that runs check.py every 15 minutes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_LABEL="com.$(whoami).fatigue-monitor"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
UV_PATH="$(command -v uv 2>/dev/null || echo "")"
LOG_DIR="$HOME/.local/share/fatigue-monitor"

# ---- 前提チェック ----
echo "=== fatigue-monitor installer ==="

if [ -z "$UV_PATH" ]; then
  echo "Error: uv not found. Install it from https://docs.astral.sh/uv/"
  exit 1
fi
echo "uv:   $UV_PATH"
echo "script: $SCRIPT_DIR/check.py"
echo "plist:  $PLIST_DEST"
echo ""

# ---- .env チェック ----
ENV_FILE="$HOME/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Warning: ~/.env not found."
  echo "Copy .env.example to ~/.env and set GEMINI_API_KEY and DISCORD_WEBHOOK_URL."
  echo ""
fi

# ---- ログディレクトリ作成 ----
mkdir -p "$LOG_DIR"

# ---- 既存の plist をアンロード ----
if launchctl list "$PLIST_LABEL" &>/dev/null; then
  echo "Unloading existing agent..."
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# ---- plist 生成 ----
cat > "$PLIST_DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
      <string>${UV_PATH}</string>
      <string>run</string>
      <string>--script</string>
      <string>${SCRIPT_DIR}/check.py</string>
    </array>

    <!-- Run every 15 minutes (900 seconds) -->
    <key>StartInterval</key>
    <integer>900</integer>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/fatigue-monitor.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/fatigue-monitor.log</string>

    <key>ProcessType</key>
    <string>Background</string>

    <!-- Inherit the user's environment (for PATH, pyenv, etc.) -->
    <key>EnvironmentVariables</key>
    <dict>
      <key>HOME</key>
      <string>${HOME}</string>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
  </dict>
</plist>
EOF

# ---- エージェントをロード ----
launchctl load "$PLIST_DEST"
echo "Installed and started: $PLIST_LABEL"
echo ""
echo "Logs: $LOG_DIR/fatigue-monitor.log"
echo ""
echo "Commands:"
echo "  Manual run:    uv run --script $SCRIPT_DIR/check.py"
echo "  Dry run:       uv run --script $SCRIPT_DIR/check.py --dry-run"
echo "  Reset state:   uv run --script $SCRIPT_DIR/check.py --reset"
echo "  View logs:     tail -f $LOG_DIR/fatigue-monitor.log"
echo "  Uninstall:     launchctl unload $PLIST_DEST && rm $PLIST_DEST"
