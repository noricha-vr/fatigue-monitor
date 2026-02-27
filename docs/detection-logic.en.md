# Detection Logic

[日本語版](detection-logic.md)

## Overview

Each run performs a two-stage evaluation to minimize Gemini API calls.

```
Messages collected
    └─ Stage 1: Heuristic filter
            ├─ No issues → score=0.0, done (no API call)
            └─ Suspicious → Stage 2: Gemini evaluation
                    ├─ score < threshold → log, no notification
                    └─ score ≥ threshold → Discord + TTS alert
```

---

## Stage 1 – Heuristic Filter

Three conditions are checked independently. **Any one match** marks the session as suspicious and triggers Stage 2.

Before the three checks, a guard is applied: if the message count is below `MIN_MESSAGES` (default: 3), the run is skipped entirely.

### Condition 1 – Prompt length drop

Messages are split into a first half and second half. The average character count of each half is compared:

```
drop_ratio = (first_half_avg - second_half_avg) / first_half_avg
```

Triggers if `drop_ratio ≥ PROMPT_LENGTH_DROP_RATIO` (default: 0.30, i.e. 30%).

**Detects**: Prompts becoming shorter and less precise as fatigue sets in.

### Condition 2 – Session duration

```
session_min = (latest_message_ts - earliest_message_ts) / 60
```

Triggers if `session_min ≥ SESSION_LONG_MIN` (default: 180 minutes).

**Detects**: Working for an extended period without a break.

### Condition 3 – Late-night hours

```python
is_late = hour >= LATE_NIGHT_HOUR_START or hour < LATE_NIGHT_HOUR_END
# Default: hour >= 22 or hour < 5
```

**Detects**: Coding late at night when cognitive performance is reduced.

---

## Stage 2 – Gemini API Evaluation

### What is sent

The following data is included in a single API call to `gemini-2.0-flash`:

**Session statistics**

| Field | Description |
|-------|-------------|
| `message_count` | Total messages in this check window |
| `avg_prompt_length` | Average prompt length in characters |
| `prompt_length_drop_ratio` | Drop ratio between first and second half (%) |
| `session_duration_min` | Session duration in minutes |
| `is_late_night` | Whether the current time is in the late-night range |

**Recent prompts**

The last 10 messages, each truncated to 300 characters, formatted as:

```
[1] (claude-code) prompt text up to 300 chars
[2] (codex) prompt text up to 300 chars
...
```

The source (`claude-code` or `codex`) is included per entry.

### What is returned

```json
{"score": 7.5, "reason": "prompts getting shorter and vague"}
```

| Field | Description |
|-------|-------------|
| `score` | Fatigue level from 0.0 to 10.0 |
| `reason` | Explanation in 40 characters or fewer |

`responseMimeType: "application/json"` and `temperature: 0.1` are set to keep output deterministic.

### Privacy

Only the last 10 prompts (≤ 300 chars each) and aggregate statistics are transmitted. Full conversation history never leaves your machine.
