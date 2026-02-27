# fatigue-monitor

Watches your [Claude Code](https://claude.ai/code) and [Codex CLI](https://github.com/openai/codex) conversation history, detects when you're getting tired, and sends you a voice + Discord alert before you ship something you'll regret.

## How it works

Every 15 minutes a background job reads the JSONL conversation logs and runs a two-stage check:

1. **Heuristic filter** – checks prompt length trends, session duration, and late-night hours. Skips the LLM call if everything looks fine (saves API cost).
2. **Gemini Flash evaluation** – if the heuristic flags a concern, sends the recent prompts to Gemini 2.0 Flash for a fatigue score (0–10).
3. **Alerts** – if the score ≥ threshold (default 7.0):
   - Discord Webhook embed with score, reason, and session stats
   - Japanese voice alert via Gemini TTS (`speak.sh`)

Conversation sources:
| Source | Location |
|--------|----------|
| Claude Code | `~/.claude/projects/**/*.jsonl` |
| Codex CLI | `~/.codex/history.jsonl` |

## Requirements

- macOS (uses `launchd` for scheduling)
- [uv](https://docs.astral.sh/uv/) – no other Python setup needed
- Gemini API key ([get one](https://aistudio.google.com/app/apikey))
- Discord Webhook URL (Server Settings → Integrations → Webhooks)
- (Optional) [`speak.sh`](https://github.com/noricha-vr/dotfiles) for Gemini TTS voice alerts

## Installation

```bash
# 1. Clone
git clone https://github.com/noricha-vr/fatigue-monitor.git
cd fatigue-monitor

# 2. Set up environment variables
cp -n .env.example ~/.env   # -n: do not overwrite if ~/.env already exists
# Or append only the new keys:
# cat .env.example >> ~/.env
#   edit ~/.env and fill in GEMINI_API_KEY and DISCORD_WEBHOOK_URL

# 3. Install launchd agent (runs every 15 minutes)
bash install.sh
```

## Manual usage

```bash
# Incremental check (since last run)
uv run --script check.py

# Evaluate without sending notifications
uv run --script check.py --dry-run

# Reset state and re-evaluate all history
uv run --script check.py --reset
```

## Configuration

All settings are optional and can be overridden via environment variables in `~/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | – | **Required.** Gemini API key |
| `DISCORD_WEBHOOK_URL` | – | **Required.** Discord Webhook URL |
| `SPEAK_SCRIPT_PATH` | `~/.claude/skills/speak/speak.sh` | Path to Gemini TTS script |
| `FATIGUE_THRESHOLD` | `7.0` | Score threshold for alerts (0–10) |
| `MIN_MESSAGES` | `3` | Minimum messages before evaluating |
| `PROMPT_LENGTH_DROP_RATIO` | `0.3` | Prompt length drop ratio to trigger LLM (30%) |
| `SESSION_LONG_MIN` | `180` | Session duration (minutes) to trigger LLM |
| `LATE_NIGHT_HOUR_START` | `22` | Late-night start hour |
| `LATE_NIGHT_HOUR_END` | `5` | Late-night end hour |

## Data & privacy

- Conversation history stays on your machine. Only the **last 10 prompts** (truncated to 300 chars each) are sent to the Gemini API for scoring.
- State file: `~/.local/share/fatigue-monitor/state.json`
- Evaluation log: `~/.local/share/fatigue-monitor/log.jsonl`
- Daemon log: `~/.local/share/fatigue-monitor/fatigue-monitor.log`

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.$(whoami).fatigue-monitor.plist
rm ~/Library/LaunchAgents/com.$(whoami).fatigue-monitor.plist
```

## License

MIT
