# Providers

JARVIS routes across multiple LLM/TTS providers with automatic failover and
credit monitoring. This document explains how each provider's key is obtained,
how its remaining credit is checked, and the free-tier assumptions behind the
rolling local estimates.

## LLM providers

All providers except local Ollama speak the OpenAI-compatible chat-completions
protocol, so the adapter layer is thin. Set keys in `.env` or in the Settings UI
(they are stored masked in a gitignored local store).

| Provider | Env key | Base URL | Credit check | Free tier (estimate) |
|---|---|---|---|---|
| NVIDIA NIM | `NVIDIA_API_KEY` | `https://integrate.api.nvidia.com/v1` | No usage endpoint → local estimate | ~5M tokens/mo (variable) |
| Groq | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | No usage endpoint → local estimate | rate-limited free tier |
| Cerebras | `CEREBRAS_API_KEY` | `https://api.cerebras.ai/v1` | No usage endpoint → local estimate | ~$5 free / variable |
| OpenCode Zen | `OPENCODE_ZEN_API_KEY` | `https://opencode.ai/api/v1` | No usage endpoint → local estimate | subscription/credits |
| Ollama Cloud | `OLLAMA_CLOUD_API_KEY` | `https://ollama.com/api` | No usage endpoint → local estimate | free/credits |
| Ollama (local) | none | `http://127.0.0.1:11434` | n/a — infinite (local) | always |

### How credit monitoring works

1. **Providers with a usage endpoint** (`has_credit_endpoint == True`): the
   router calls `check_credit()` against the provider's billing/usage API.
   None of the currently supported providers expose one publicly, so all six
   use the local estimate path today — the interface is ready for providers
   that do.

2. **Providers without an endpoint**: the router tracks a rolling local
   estimate. Every `chat()` call records prompt + completion token counts into
   `~/.jarvis/usage.json` (gitignored, chmod 600). Remaining credit is
   `1 - used/free_budget`. These are **estimates, not facts** — the GUI marks
   them as such.

3. **Threshold**: `CREDIT_LOW_THRESHOLD` (default `0.10`). When a provider's
   estimate drops below this, JARVIS speaks a warning and fails over to the
   next provider mid-conversation without dropping context.

4. **Failover order** is user-reorderable in Settings (`PROVIDER_PRIORITY`).
   Local Ollama is always the last resort and treated as infinite.

5. **On hard errors** (401 invalid key, 429 rate-limited, insufficient quota)
   the router switches immediately, logs the switch in the activity panel, and
   updates the status bar.

> Note on free-tier budgets: these are rough, community-known figures and
> change often. They exist so JARVIS can warn *before* a provider starts
> erroring. Treat them as estimates; adjust via the usage store if you use
> JARVIS heavily.

## TTS providers

| Provider | Env key | Role | Credit/fallback |
|---|---|---|---|
| Fish Audio | `FISH_AUDIO_API_KEY` | Primary | On 401/402/403/quota error → fallback to local |
| Local TTS (`say`/`espeak`) | `LOCAL_TTS_VOICE`, `LOCAL_TTS_RATE` | Fallback | Always available, free |

Fish Audio errors (auth, payment, quota) trigger an automatic switch to local
software TTS so JARVIS never goes silent. The `say` output on macOS is converted
to WAV via ffmpeg (or an internal AIFF→WAV converter if ffmpeg is missing).

## STT

`faster-whisper` runs locally (CPU). No API key, no cost, no credit to track.
Model size via `STT_MODEL` (tiny/base/small/medium). Chosen over paid STT so
voice input never depends on a billable service. Alternatives: Apple Speech
framework (via a future native plugin) or Whisper.cpp.

## Web search

Built-in DuckDuckGo HTML search needs **no key**. If `BRAVE_API_KEY` is set,
Brave Search API is used instead.

## Vision

Vision uses whichever OpenAI-compatible provider has a key, preferring a
vision-capable model. Override with `VISION_API_KEY`, `VISION_BASE_URL`,
`VISION_MODEL` if needed. Video is handled by extracting frames with ffmpeg and
summarizing them with the vision model.
