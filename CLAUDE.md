# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

macOS 専用のデベロッパー疲労検知ツール。Claude Code / Codex CLI の会話ログを読み、Gemini Flash で疲労スコアを評価し、Discord Webhook + Gemini TTS で警告する。

- **全ロジックは `check.py` 1 ファイルに集約**（依存: `python-dotenv` のみ）
- スケジューリングは launchd（`install.sh` で設定）
- 環境変数は `~/.env` から読み込む（プロジェクト内の `.env` は使わない）

## Commands

```bash
# 手動実行（前回チェック以降の増分評価）
uv run --script check.py

# 通知をスキップしてスコアだけ確認
uv run --script check.py --dry-run

# state.json を削除して全履歴を再評価
uv run --script check.py --reset

# launchd デーモンのログ確認
tail -f ~/.local/share/fatigue-monitor/fatigue-monitor.log

# デーモン起動状態の確認
launchctl list | grep fatigue
```

## Architecture

### 2段階評価フロー

1. **ヒューリスティックフィルタ**（API コスト削減）
   - プロンプト長の後半ドロップ率 ≥ 30%
   - セッション継続時間 ≥ 180 分
   - 深夜帯（22:00–5:00）
   - いずれかに該当すれば Stage 2 へ進む

2. **Gemini 2.0 Flash 評価**
   - 最新 10 件のプロンプト（各 300 文字以内）をセッション統計とともに送信
   - 0–10 のスコアと理由を JSON で返す

3. **アラート**（score ≥ 7.0）
   - Discord Webhook embed
   - Gemini TTS (`gemini-2.5-flash-preview-tts`, voice: Kore) → PCM を `wave` で WAV 変換 → `afplay` 再生（ffmpeg 不要）

### 会話ログ収集元

| ソース | パス |
|--------|------|
| Claude Code | `~/.claude/projects/**/*.jsonl` |
| Codex CLI | `~/.codex/history.jsonl` |

除外条件: `!` 始まりのシェルコマンド、`[Request interrupted by user]`

### データファイル

| ファイル | 用途 |
|----------|------|
| `~/.local/share/fatigue-monitor/state.json` | 前回チェックのタイムスタンプ |
| `~/.local/share/fatigue-monitor/log.jsonl` | 評価ログ（1 実行 1 行） |
| `~/.local/share/fatigue-monitor/fatigue-monitor.log` | launchd stdout/stderr |

## Environment Variables

`~/.env` に設定する（プロジェクトの `.env` は使用しない）:

| 変数 | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `GEMINI_API_KEY` | 必須 | - | LLM 評価 + TTS 両方に使用 |
| `DISCORD_WEBHOOK_URL` | 必須 | - | `https://discord.com/api/webhooks/` で始まること |
| `FATIGUE_THRESHOLD` | 任意 | `7.0` | アラート閾値 |
| `MIN_MESSAGES` | 任意 | `3` | 評価に必要な最小メッセージ数 |
| `PROMPT_LENGTH_DROP_RATIO` | 任意 | `0.3` | Stage 2 を起動するドロップ率 |
| `SESSION_LONG_MIN` | 任意 | `180` | セッション時間閾値（分） |
| `LATE_NIGHT_HOUR_START` | 任意 | `22` | 深夜開始時刻 |
| `LATE_NIGHT_HOUR_END` | 任意 | `5` | 深夜終了時刻 |

## Installation / Uninstall

```bash
# インストール（launchd エージェントを登録）
bash install.sh

# アンインストール
launchctl unload ~/Library/LaunchAgents/com.$(whoami).fatigue-monitor.plist
rm ~/Library/LaunchAgents/com.$(whoami).fatigue-monitor.plist
```
