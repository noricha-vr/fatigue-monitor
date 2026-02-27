#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["python-dotenv"]
# ///
"""fatigue-monitor: アラート音声ファイルの事前生成スクリプト

Gemini TTS Pro で固定フレーズの WAV ファイルを生成し、
~/.local/share/fatigue-monitor/alert.wav に保存する。

Usage:
    uv run --script generate_audio.py

Environment variables (loaded from ~/.env):
    GEMINI_API_KEY  - Required: Gemini API key
"""

import base64
import json
import os
import sys
import wave
from pathlib import Path
from urllib import request

from dotenv import load_dotenv

MONITOR_DIR = Path.home() / ".local" / "share" / "fatigue-monitor"
ALERT_AUDIO_FILE = MONITOR_DIR / "alert.wav"

ALERT_TEXT = "疲れていませんか？少し休んでみてはいかがでしょうか。"
TTS_MODEL = "gemini-2.5-pro-preview-tts"
TTS_VOICE = "Kore"


def generate_alert_audio(api_key: str) -> bytes:
    """Gemini TTS Pro でアラート音声 PCM データを生成する。"""
    payload = {
        "contents": [{"parts": [{"text": ALERT_TEXT}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": TTS_VOICE}
                }
            },
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{TTS_MODEL}:generateContent"
    )
    req = request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    audio_b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    return base64.b64decode(audio_b64)


def save_wav(pcm_data: bytes, path: Path):
    """PCM データ（s16le 24kHz mono）を WAV ファイルとして保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)      # モノラル
        wav.setsampwidth(2)      # 16bit
        wav.setframerate(24000)  # 24kHz
        wav.writeframes(pcm_data)


def main():
    load_dotenv(Path.home() / ".env", override=False)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Error: GEMINI_API_KEY is not set in ~/.env", file=sys.stderr)
        sys.exit(1)

    print(f"Generating alert audio with {TTS_MODEL} (voice: {TTS_VOICE})...")
    print(f"Text: {ALERT_TEXT}")

    try:
        pcm_data = generate_alert_audio(api_key)
    except Exception as e:
        print(f"Error: TTS API call failed - {e}", file=sys.stderr)
        sys.exit(1)

    save_wav(pcm_data, ALERT_AUDIO_FILE)
    print(f"Saved: {ALERT_AUDIO_FILE}")


if __name__ == "__main__":
    main()
