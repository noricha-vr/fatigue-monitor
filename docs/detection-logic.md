# 検知ロジック

[English version](detection-logic.en.md)

## 概要

API 呼び出しを最小限に抑えるため、毎回 2 段階評価を行う。

```
メッセージを収集
    └─ Stage 1: ヒューリスティックフィルタ
            ├─ 問題なし → score=0.0、終了（API 呼び出しなし）
            └─ 疑わしい → Stage 2: Gemini 評価
                    ├─ score < 閾値 → ログのみ、通知なし
                    └─ score ≥ 閾値 → Discord + TTS アラート
```

---

## Stage 1 – ヒューリスティックフィルタ

3 つの条件を独立にチェックし、**1 つでも該当すれば**「疑わしい」と判定して Stage 2 へ進む。

3 条件のチェック前に事前ガードがある: メッセージ数が `MIN_MESSAGES`（デフォルト: 3）未満の場合は実行をスキップする。

### 条件 1 – プロンプト長のドロップ

メッセージを前半・後半に二分割し、それぞれの平均文字数を比較する:

```
drop_ratio = (前半平均 - 後半平均) / 前半平均
```

`drop_ratio ≥ PROMPT_LENGTH_DROP_RATIO`（デフォルト: 0.30、30%）で発動。

**検出対象**: 疲れによってプロンプトが短く・雑になっている状態。

### 条件 2 – セッション継続時間

```
session_min = (最新メッセージの ts - 最古メッセージの ts) / 60
```

`session_min ≥ SESSION_LONG_MIN`（デフォルト: 180 分）で発動。

**検出対象**: 休憩なしの長時間作業。

### 条件 3 – 深夜帯

```python
is_late = hour >= LATE_NIGHT_HOUR_START or hour < LATE_NIGHT_HOUR_END
# デフォルト: hour >= 22 or hour < 5
```

**検出対象**: 認知パフォーマンスが低下する深夜帯のコーディング。

---

## Stage 2 – Gemini API 評価

### 送信する情報

`gemini-2.0-flash` への 1 回の API 呼び出しに以下のデータを含める:

**セッション統計**

| フィールド | 説明 |
|-----------|------|
| `message_count` | 今回のチェック対象メッセージ総数 |
| `avg_prompt_length` | 平均プロンプト文字数 |
| `prompt_length_drop_ratio` | 前半・後半のドロップ率（%） |
| `session_duration_min` | セッション継続時間（分） |
| `is_late_night` | 現在時刻が深夜帯かどうか |

**直近のプロンプト**

最新 10 件のメッセージを各 300 文字にトランケートし、以下の形式でまとめる:

```
[1] (claude-code) プロンプト本文（最大 300 文字）
[2] (codex) プロンプト本文（最大 300 文字）
...
```

各行にソース（`claude-code` または `codex`）が付く。

### 返ってくる内容

```json
{"score": 7.5, "reason": "prompts getting shorter and vague"}
```

| フィールド | 説明 |
|-----------|------|
| `score` | 疲労度（0.0〜10.0） |
| `reason` | 40 文字以内の理由（英語） |

出力のブレを最小化するため `responseMimeType: "application/json"` と `temperature: 0.1` を指定している。

### プライバシー

送信されるのは最新 10 件のプロンプト（各 300 文字以内）と集計統計のみ。会話履歴の全文はローカルマシンから外に出ない。
