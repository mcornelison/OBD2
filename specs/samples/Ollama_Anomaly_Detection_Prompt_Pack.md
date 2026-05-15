# Ollama Prompt Pack: Anomaly Detection & Explanations (OBD-II Telemetry)

This document captures a **deterministic-anomaly-first + LLM-explanation-second** design for post-drive analytics using Ollama, with **auditable JSON outputs** and **source citations**.

> **Key principle:** Detect anomalies with deterministic code (features/rules), then use the LLM to *explain* flagged anomalies using **only the provided evidence**.

---

## 1) Mental Model (Why this works)

**Do not** ask the LLM to detect anomalies directly from raw telemetry.

**Do**:

```
Raw telemetry → deterministic feature extraction → anomaly flags
                                             ↓
                                      LLM explanation
```

The LLM receives **small evidence packets** (baseline metrics + observed metrics + correlated signals + vehicle context) and must reason only from that data.

---

## 2) Canonical SYSTEM Prompt (Use Everywhere)

Use this as the system message for all anomaly/explanation tasks.

```text
You are an automotive diagnostic analyst assisting with post-drive analysis.

Rules:
- You MUST reason only from the data provided.
- You MUST NOT invent sensor values, events, or failures.
- If evidence is insufficient, say "Insufficient evidence".
- Distinguish between:
  - benign behavior
  - watch / monitor
  - investigate soon
- Favor proportional, conservative conclusions.

Context:
- Vehicle: 1998 Mitsubishi Eclipse GST Turbo
- Data source: OBD-II telemetry and derived analytics
- Data is incomplete by design; missing sensors are normal.
- This analysis is informational, not a repair diagnosis.

Output requirements:
- Respond ONLY in valid JSON.
- Do not include extra commentary or prose.
- Use short, precise explanations.
```

**Why JSON?** Ollama supports JSON-formatted responses using the `format` parameter (JSON mode), and the docs note you should explicitly instruct the model to produce JSON for reliable structured output. citeturn2search88

---

## 3) Prompt Template A — Anomaly Explanation (Core)

### When to use
- Your deterministic analytics has already flagged an anomaly.
- You want the LLM to provide: meaning, risk framing, likely explanations, and recommended next steps.

### Input (what you send to the model)

```json
{
  "task": "explain_anomaly",
  "anomaly": {
    "id": "coolant_temp_slope_high",
    "severity": "watch",
    "description": "Coolant temperature increased faster than baseline during steady driving"
  },
  "baseline": {
    "coolant_temp_rise_rate_f_per_min": 1.8,
    "ambient_temp_f": 72,
    "vehicle_speed_range_mph": "45–55"
  },
  "observed": {
    "coolant_temp_rise_rate_f_per_min": 4.9,
    "max_coolant_temp_f": 226,
    "duration_minutes": 6.2,
    "throttle_position_percent": "steady"
  },
  "correlated_signals": {
    "vehicle_speed_mph": "steady",
    "intake_air_temp_f": "normal",
    "battery_voltage_v": "normal"
  },
  "known_context": {
    "recent_maintenance": "cooling system serviced 14 months ago",
    "mods": "aftermarket intercooler"
  }
}
```

### Output (expected JSON shape)

```json
{
  "summary": "Coolant temperature rose more quickly than baseline under conditions that typically allow stable cooling.",
  "risk_level": "watch",
  "likely_explanations": [
    "Reduced airflow at radiator",
    "Cooling fan engagement delay",
    "Natural variance due to ambient or load differences"
  ],
  "less_likely_explanations": [
    "Coolant loss",
    "Water pump failure"
  ],
  "recommended_actions": [
    "Monitor for recurrence on similar routes",
    "Verify radiator fan operation when parked",
    "Check coolant level at next service interval"
  ],
  "confidence": 0.78
}
```

### Notes (design constraints)
- The model must **not** invent data. If the evidence does not support a claim, it must respond with uncertainty or “Insufficient evidence.”
- Keep recommendations proportional (watch vs investigate) and tied to the evidence packet.

---

## 4) Prompt Template B — Drive-Level Summary (For “Drive Reports”)

### Purpose
Generate a narrative summary suitable for storage, playback, or indexing for later retrieval.

### Input

```json
{
  "task": "drive_summary",
  "trip_metadata": {
    "date": "2026-05-14",
    "duration_minutes": 42,
    "driving_type": "mixed city / highway"
  },
  "highlights": {
    "max_rpm": 5200,
    "max_coolant_temp_f": 228,
    "min_battery_voltage_v": 12.1
  },
  "detected_events": [
    {
      "event": "coolant_temp_slope_high",
      "severity": "watch",
      "timestamp_minute": 18
    },
    {
      "event": "voltage_dip",
      "severity": "benign",
      "timestamp_minute": 33
    }
  ],
  "overall_health_assessment": "generally normal with minor items to monitor"
}
```

### Output

```json
{
  "narrative": "This drive was generally normal. Engine performance stayed within expected limits. A brief coolant temperature rise occurred mid-drive, which may warrant monitoring on future trips, but no immediate action is required. Electrical system behavior was stable, with a short voltage dip consistent with transient accessory load.",
  "tone": "neutral",
  "recommended_follow_up": [
    "Re-check coolant behavior on similar ambient conditions",
    "No immediate mechanical action required"
  ],
  "embedding_hint": "coolant temperature trend during steady cruise"
}
```

---

## 5) Prompt Template C — “Ask My Drives” (RAG-Style Q&A)

### Flow
1) Embed the user’s question.
2) Vector-search trip summaries and anomaly explanations.
3) Provide top-K retrieved items to the LLM as context.

Ollama provides an embeddings capability and recommends embedding models (e.g., `embeddinggemma`, `qwen3-embedding`, `all-minilm`) for semantic search / retrieval use cases. citeturn2search42

### Input

```json
{
  "task": "answer_question",
  "question": "Has my cooling system been getting worse over time?",
  "retrieved_context": [
    {
      "trip_date": "2026-04-30",
      "summary": "Coolant behavior normal under mixed driving."
    },
    {
      "trip_date": "2026-05-07",
      "summary": "Slightly elevated coolant rise rate under steady cruise."
    },
    {
      "trip_date": "2026-05-14",
      "summary": "Repeated coolant rise anomaly during steady driving."
    }
  ]
}
```

### Output

```json
{
  "answer": "There is a mild upward trend in coolant temperature rise rate across recent drives, but values remain below critical thresholds.",
  "trend_assessment": "gradual change",
  "confidence": 0.73,
  "recommended_monitoring": [
    "Continue tracking coolant slope over the next 3–5 similar drives"
  ]
}
```

---

## 6) Ollama API Call Guidance (Grounded)

### 6.1 `/api/generate` (JSON mode)
The Ollama API reference documents `POST /api/generate`, including support for structured output via the `format` parameter (JSON mode) and notes that streaming can be disabled by setting `stream: false`. It also documents `keep_alive` to control how long the model remains loaded after a request. citeturn2search88

**Minimal example request body (conceptual):**

```json
{
  "model": "<your-model>",
  "prompt": "<your prompt including the JSON-only instruction>",
  "format": "json",
  "stream": false,
  "keep_alive": "10m"
}
```

> **Model naming:** Ollama model names follow a `model:tag` format (tag optional, defaulting to `latest`), as documented in the API reference. citeturn2search88

### 6.2 `/api/embed` (Embeddings)
Ollama documents `POST /api/embed` for generating embeddings, including:
- `model` (required)
- `input` as a string or array of strings
- `truncate` behavior
- optional `dimensions` and `keep_alive`
- response fields like `embeddings`, `total_duration`, and `prompt_eval_count` citeturn2search87

**Example request (from docs):** citeturn2search87

```json
{
  "model": "embeddinggemma",
  "input": "Why is the sky blue?"
}
```

**What embeddings are for:** Ollama’s embeddings capability is described for semantic search, retrieval, and RAG workflows. citeturn2search42

---

## 7) Optional: GPU Notes (If you’re running Ollama on NVIDIA)

Ollama’s hardware support documentation describes:
- NVIDIA GPU support requirements (compute capability 5.0+ and driver version 531+).
- GPU selection via `CUDA_VISIBLE_DEVICES` to limit Ollama to a subset of GPUs.
- How to discover GPU UUIDs using `nvidia-smi -L`. citeturn1search69turn1search72

---

## 8) Source Links (for human reading)

- Ollama API reference (generate / JSON mode / keep_alive): [Ollama API Reference](https://ollama.readthedocs.io/en/api/)
- Ollama API embed endpoint: [Generate embeddings (POST /api/embed)](https://docs.ollama.com/api/embed)
- Ollama embeddings capability overview: [Embeddings capability](https://docs.ollama.com/capabilities/embeddings)
- Ollama GPU support: [Hardware support (GPU)](https://docs.ollama.com/gpu)
- Ollama GPU doc in repo: [gpu.mdx (GitHub)](https://github.com/ollama/ollama/blob/main/docs/gpu.mdx)

---

## 9) Implementation Tips (Non-cited, design guidance)

The following are **architectural suggestions** (not directly specified in the cited sources):

- Store raw telemetry in MySQL time-series tables; store derived anomalies/events and narrative summaries separately.
- Embed only summaries and event descriptions (not raw series) for fast semantic retrieval.
- Treat the LLM as an “analyst” that explains flagged events, not as the detector.

