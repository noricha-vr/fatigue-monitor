#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["python-dotenv"]
# ///
"""fatigue-monitor: Developer fatigue detection for Claude Code / Codex CLI

Reads conversation history from Claude Code (~/.claude/projects/) and
Codex CLI (~/.codex/history.jsonl), evaluates fatigue level via Gemini Flash,
and sends alerts via Discord Webhook + Gemini TTS when the score exceeds the threshold.

Usage:
    uv run check.py          # incremental check (since last run)
    uv run check.py --reset  # reset state and re-evaluate all history

Environment variables (loaded from ~/.env):
    GEMINI_API_KEY          - Required: Gemini API key
    DISCORD_WEBHOOK_URL     - Required: Discord Webhook URL
    FATIGUE_THRESHOLD       - Optional: score threshold for alerts (default: 7.0)
    MIN_MESSAGES            - Optional: minimum messages to evaluate (default: 3)
    PROMPT_LENGTH_DROP_RATIO- Optional: length drop ratio to trigger LLM (default: 0.3)
    SESSION_LONG_MIN        - Optional: session duration threshold in minutes (default: 180)
    LATE_NIGHT_HOUR_START   - Optional: late-night start hour (default: 22)
    LATE_NIGHT_HOUR_END     - Optional: late-night end hour (default: 5)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from urllib import request
from urllib.error import URLError

from dotenv import load_dotenv

# --- 設定（環境変数で上書き可能）---
MONITOR_DIR = Path.home() / ".local" / "share" / "fatigue-monitor"
STATE_FILE = MONITOR_DIR / "state.json"
LOG_FILE = MONITOR_DIR / "log.jsonl"

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CODEX_HISTORY_FILE = Path.home() / ".codex" / "history.jsonl"

DISCORD_WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"


def get_config() -> dict:
    """環境変数から設定を読み込む。"""
    return {
        "fatigue_threshold": float(os.environ.get("FATIGUE_THRESHOLD", "7.0")),
        "min_messages": int(os.environ.get("MIN_MESSAGES", "3")),
        "prompt_length_drop_ratio": float(os.environ.get("PROMPT_LENGTH_DROP_RATIO", "0.3")),
        "session_long_min": int(os.environ.get("SESSION_LONG_MIN", "180")),
        "late_night_start": int(os.environ.get("LATE_NIGHT_HOUR_START", "22")),
        "late_night_end": int(os.environ.get("LATE_NIGHT_HOUR_END", "5")),
    }


# --- 状態管理（増分チェック用）---
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_check_ts": 0.0}


def save_state(state: dict):
    MONITOR_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# --- メッセージ抽出 ---
def extract_claude_messages(since_ts: float) -> list[dict]:
    """Claude Code の JSONL からユーザーメッセージを抽出する。"""
    messages = []
    for jsonl_file in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        try:
            with open(jsonl_file, errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("type") != "user":
                        continue
                    ts_str = entry.get("timestamp", "")
                    if not ts_str:
                        continue
                    msg_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                    if msg_ts <= since_ts:
                        continue

                    content = entry.get("message", {}).get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            c.get("text", "") for c in content if isinstance(c, dict)
                        )
                    content = str(content).strip()
                    if content and content != "[Request interrupted by user]":
                        messages.append({"ts": msg_ts, "text": content, "source": "claude-code"})
        except Exception as e:
            print(f"Warning: {jsonl_file}: {e}", file=sys.stderr)
            continue
    return messages


def extract_codex_messages(since_ts: float) -> list[dict]:
    """Codex CLI の history.jsonl からユーザーメッセージを抽出する。"""
    messages = []
    if not CODEX_HISTORY_FILE.exists():
        return messages
    try:
        with open(CODEX_HISTORY_FILE, errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                msg_ts = float(entry.get("ts", 0))
                if msg_ts <= since_ts:
                    continue
                text = entry.get("text", "").strip()
                # シェルコマンド（! 始まり）は除外
                if text and not text.startswith("!"):
                    messages.append({"ts": msg_ts, "text": text, "source": "codex"})
    except Exception as e:
        print(f"Warning: {e}", file=sys.stderr)
    return messages


# --- ヒューリスティックフィルタ（API コスト削減）---
def heuristic_check(messages: list[dict], cfg: dict) -> tuple[bool, dict]:
    """LLM を呼ぶ前に疲れのサインを簡易チェックする。

    Returns:
        (suspicious, stats_dict)
    """
    if len(messages) < cfg["min_messages"]:
        return False, {"reason": f"only {len(messages)} messages (< {cfg['min_messages']})"}

    lengths = [len(m["text"]) for m in messages]
    avg_len = sum(lengths) / len(lengths)

    # 前半 vs 後半のプロンプト長比較
    half = max(len(lengths) // 2, 1)
    first_half_avg = sum(lengths[:half]) / half
    second_half_avg = sum(lengths[half:]) / max(len(lengths) - half, 1)
    length_drop = (
        (first_half_avg - second_half_avg) / first_half_avg
        if first_half_avg > 0
        else 0.0
    )

    # セッション時間（分）
    session_min = (
        (messages[-1]["ts"] - messages[0]["ts"]) / 60 if len(messages) > 1 else 0
    )

    # 深夜判定
    hour = datetime.now().hour
    is_late = hour >= cfg["late_night_start"] or hour < cfg["late_night_end"]

    stats = {
        "message_count": len(messages),
        "avg_prompt_length": round(avg_len),
        "prompt_length_drop_ratio": round(length_drop, 2),
        "session_duration_min": round(session_min),
        "is_late_night": is_late,
        "sources": sorted({m["source"] for m in messages}),
    }

    suspicious = (
        length_drop >= cfg["prompt_length_drop_ratio"]
        or session_min >= cfg["session_long_min"]
        or is_late
    )
    return suspicious, stats


# --- Gemini Flash で疲労度評価 ---
def evaluate_fatigue(messages: list[dict], stats: dict) -> dict:
    """Gemini Flash にユーザーの疲労度スコアを評価させる。

    Returns:
        {"score": float, "reason": str}
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    # 最新 10 件を提示
    recent = messages[-10:]
    prompt_texts = "\n".join(
        f"[{i + 1}] ({m['source']}) {m['text'][:300]}" for i, m in enumerate(recent)
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"""The following are recent prompts from a developer actively coding.
Evaluate whether the user appears to be fatigued.

Stats:
- Message count: {stats['message_count']}
- Average prompt length: {stats['avg_prompt_length']} chars
- Prompt length drop ratio: {stats['prompt_length_drop_ratio'] * 100:.0f}%
- Session duration: {stats['session_duration_min']} min
- Late night: {'yes' if stats['is_late_night'] else 'no'}

Recent prompts:
{prompt_texts}

Rate fatigue from 0.0 to 10.0 and explain the reason in 40 characters or fewer.
Return ONLY valid JSON:
{{"score": 7.5, "reason": "prompts getting shorter and vague"}}"""
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash:generateContent"
    )
    req = request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    with request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


# --- Discord 通知（理由付き）---
def notify_discord(score: float, reason: str, stats: dict):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set, skipping", file=sys.stderr)
        return

    if not webhook_url.startswith(DISCORD_WEBHOOK_PREFIX):
        print(
            f"Error: DISCORD_WEBHOOK_URL must start with {DISCORD_WEBHOOK_PREFIX}",
            file=sys.stderr,
        )
        return

    late_str = "yes (late night)" if stats["is_late_night"] else "no"
    sources = ", ".join(stats.get("sources", []))

    payload = {
        "embeds": [
            {
                "title": f"Fatigue Alert (score: {score:.1f} / 10)",
                "description": f"**{reason}**\n\nTime to take a break!",
                "color": 0xFF6B35,
                "fields": [
                    {"name": "Messages", "value": str(stats["message_count"]), "inline": True},
                    {"name": "Avg prompt length", "value": f"{stats['avg_prompt_length']} chars", "inline": True},
                    {"name": "Session duration", "value": f"{stats['session_duration_min']} min", "inline": True},
                    {"name": "Late night", "value": late_str, "inline": True},
                    {"name": "Tools", "value": sources or "unknown", "inline": True},
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }

    req = request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10):
            pass
        print("Discord: sent")
    except URLError as e:
        print(f"Discord: failed - {e}", file=sys.stderr)


# --- Gemini TTS 音声通知 ---
def notify_tts(score: float, reason: str):
    """Gemini TTS API で音声を生成し afplay で再生する。

    PCM データ（s16le 24kHz mono）を wave モジュールで WAV に変換するため
    ffmpeg 不要。一時ファイルは再生後に自動削除。
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("GEMINI_API_KEY not set, skipping TTS", file=sys.stderr)
        return

    text = f"疲労スコア{score:.0f}です。{reason}。少し休憩してみてはいかがでしょうか？"
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": "Kore"}
                }
            },
        },
    }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash-preview-tts:generateContent"
    )
    req = request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        audio_b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        pcm_data = base64.b64decode(audio_b64)
    except Exception as e:
        print(f"TTS: API error - {e}", file=sys.stderr)
        return

    # PCM → WAV → afplay（ffmpeg 不要）
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        with wave.open(tmp_path, "wb") as wav:
            wav.setnchannels(1)     # モノラル
            wav.setsampwidth(2)     # 16bit
            wav.setframerate(24000) # 24kHz
            wav.writeframes(pcm_data)
        subprocess.run(["afplay", tmp_path], check=True, timeout=60)
        print("TTS: played")
    except Exception as e:
        print(f"TTS: playback error - {e}", file=sys.stderr)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


# --- 評価ログ保存 ---
def save_log(score: float, reason: str, stats: dict, notified: bool):
    MONITOR_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "reason": reason,
        "stats": stats,
        "notified": notified,
    }
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --- メイン ---
def main():
    parser = argparse.ArgumentParser(description="Developer fatigue monitor for Claude Code / Codex CLI")
    parser.add_argument("--reset", action="store_true", help="Reset state and re-evaluate all history")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate but skip notifications")
    args = parser.parse_args()

    load_dotenv(Path.home() / ".env", override=False)
    cfg = get_config()
    MONITOR_DIR.mkdir(parents=True, exist_ok=True)

    if args.reset:
        STATE_FILE.unlink(missing_ok=True)
        print("State reset.")

    state = load_state()
    since_ts = state["last_check_ts"]
    now_ts = datetime.now(timezone.utc).timestamp()

    since_str = datetime.fromtimestamp(since_ts).isoformat() if since_ts else "beginning"
    print(f"[fatigue-monitor] checking since {since_str}")

    # メッセージ収集
    messages = extract_claude_messages(since_ts) + extract_codex_messages(since_ts)
    messages.sort(key=lambda m: m["ts"])

    if not messages:
        print("No messages found (no activity since last check).")
        save_state({"last_check_ts": now_ts})
        print("Done.")
        return

    print(f"Collected {len(messages)} messages")

    # ヒューリスティックフィルタ
    suspicious, stats = heuristic_check(messages, cfg)
    print(f"Heuristic: {'-> LLM eval' if suspicious else 'OK'} {stats}")

    if not suspicious:
        save_log(0.0, "heuristic: no issue", stats, notified=False)
        save_state({"last_check_ts": now_ts})
        print("Done.")
        return

    # Gemini Flash で疲労度評価
    try:
        result = evaluate_fatigue(messages, stats)
        score = float(result["score"])
        reason = str(result["reason"])
    except Exception as e:
        print(f"Evaluation error: {e}", file=sys.stderr)
        return

    print(f"Fatigue score: {score:.1f}  reason: {reason}")

    # 閾値超えで通知
    notified = False
    if score >= cfg["fatigue_threshold"]:
        if args.dry_run:
            print("[dry-run] Skipping notifications.")
        else:
            notify_discord(score, reason, stats)
            notify_tts(score, reason)
        notified = not args.dry_run

    save_log(score, reason, stats, notified)
    save_state({"last_check_ts": now_ts})
    print("Done.")


if __name__ == "__main__":
    main()
