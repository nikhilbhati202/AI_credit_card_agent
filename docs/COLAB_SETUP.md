# Running the LLM in Google Colab (no paid API key required)

This project's two LLM-touching nodes (Intent Classification, Final Answer's narrative -
every other node is deterministic, see `ARCHITECTURE.md`) run against **any**
OpenAI-compatible chat-completions server, with no paid API key required. This guide runs
[Ollama](https://ollama.com/) + **Qwen2.5-7B-Instruct** in a free Google Colab GPU notebook
and tunnels it out so this project (running locally or via `docker compose`) can reach it.

Qwen2.5-7B-Instruct is the recommended model for this project specifically because it's
strong at instruction-following/JSON generation for its size - Intent Classification depends
on the model reliably returning a structured `IntentClassificationResult`, not just decent
prose.

## Known limitations (read this first)

- **Colab free-tier sessions disconnect** after ~90 minutes of inactivity and have a ~12-hour
  hard cap. Keep the notebook tab open and interact with it occasionally during a demo/dev
  session; don't expect this to stay up unattended.
- **The tunnel URL changes every time you restart** the notebook (a fresh `trycloudflare.com`
  subdomain is assigned each run) - you'll re-paste it into `.env`'s `LLM_BASE_URL` each
  session.
- This is a **development/demo setup, not a production one** - there's no auth on the tunnel
  beyond obscurity of the URL, and no uptime guarantee. Fine for interactive use exactly like
  this project's own Quickstart; not something to leave running unattended with sensitive data.
- The automated test suite (`pytest`) and the 4 evaluation gates
  (`evaluation/calculation_eval.py` etc.) don't need any of this - they either mock the LLM or
  bypass it entirely (see `EVALUATION_REPORT.md`).

## 1. Open a new Colab notebook with a GPU runtime

`Runtime → Change runtime type → T4 GPU`, then `Save`. Do this **before** running any cells
below - Ollama will fall back to CPU (much slower) otherwise.

## 2. Install and start Ollama (Colab cell)

```python
!curl -fsSL https://ollama.com/install.sh | sh
```

If this fails with `ERROR: This version requires zstd for extraction` (seen on some fresh
Colab VM images that don't ship it by default), run `!apt-get install -y zstd` first, then
retry the install command above.

```python
# Start the Ollama server in the background - a Colab cell blocks until its command exits,
# so this must be backgrounded, not run in the foreground.
import subprocess, time
subprocess.Popen(
    ["ollama", "serve"],
    stdout=open("ollama.log", "w"), stderr=subprocess.STDOUT,
)
time.sleep(5)
!curl -s http://localhost:11434/api/version
```

## 3. Pull the model

```python
!ollama pull qwen2.5:7b-instruct
```

This downloads a ~4.7GB quantized weight file - a few minutes on Colab's network. Confirm it
loaded:

```python
!ollama list
```

## 4. Expose it publicly with a Cloudflare quick tunnel (no account needed)

```python
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
!chmod +x cloudflared
```

```python
import subprocess, time
tunnel = subprocess.Popen(
    ["./cloudflared", "tunnel", "--url", "http://localhost:11434",
     "--http-host-header=localhost:11434"],
    stdout=open("cloudflared.log", "w"), stderr=subprocess.STDOUT,
)
time.sleep(8)
!grep -o "https://[a-zA-Z0-9.-]*\.trycloudflare\.com" cloudflared.log | head -1
```

**The `--http-host-header=localhost:11434` flag is required, not optional.** Ollama validates
the incoming `Host` header for security (DNS-rebinding protection) and only trusts
`localhost`/`127.0.0.1` by default - without this flag, every request through the tunnel gets
an empty `403 Forbidden` (confirmed in practice: `OLLAMA_ORIGINS` does *not* fix this, since
that variable controls CORS/browser `Origin` headers, a different mechanism; the fix has to
rewrite the `Host` header the tunnel forwards to Ollama, which is a `cloudflared` flag, not an
Ollama one). Same fix applies to ngrok: `ngrok http 11434 --host-header="localhost:11434"`.

Copy the printed URL (e.g. `https://random-words-here.trycloudflare.com`) - this is your
tunnel's base URL.

(Alternative: `pyngrok` also works and is a common Colab pattern, but recent ngrok versions
require a free account + authtoken for anything beyond a few minutes; cloudflared's quick
tunnels need no signup at all, which is why this guide defaults to it.)

## 5. Sanity-check the tunnel from anywhere (not just inside Colab)

From your own machine (where this project runs):

```bash
curl https://random-words-here.trycloudflare.com/v1/models
```

Expected: a JSON list including `qwen2.5:7b-instruct`. If this fails, the tunnel or the
Ollama server isn't up yet - re-check the Colab cells above before touching this project's
config.

## 6. Point this project at it

In `.env` (see `.env.example`):

```bash
LLM_BASE_URL=https://random-words-here.trycloudflare.com/v1
LLM_API_KEY=not-needed
LLM_INTENT_MODEL=qwen2.5:7b-instruct
LLM_FINAL_ANSWER_MODEL=qwen2.5:7b-instruct
```

Restart the app (`docker compose up -d --build app` or, for local dev,
`uvicorn backend.main:app --reload`) and try:

```bash
curl -X POST http://localhost:8000/api/v1/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "I am spending Rs. 50,000 on flights.", "cards_owned": ["Axis Atlas", "Axis ACE"]}'
```

If `intent_confidence` comes back low or the response is `insufficient_information` when it
shouldn't be, Qwen2.5 may need a slightly more explicit prompt than Claude did for structured
output - see "Troubleshooting" below before assuming something is broken.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `llm_not_configured` (503) | `LLM_BASE_URL` empty, or `.env` not reloaded | Confirm `.env` has the current tunnel URL and the app was restarted after editing it |
| `llm_unavailable` (503), connection error | Colab session disconnected, or the tunnel URL is stale | Re-run the Colab cells; you'll get a **new** tunnel URL - update `.env` again |
| `curl` to the tunnel URL returns an empty `403 Forbidden` (from `Server: cloudflare`, `Content-Length: 0`, no HTML body) | Ollama's Host-header check rejecting the tunnel's public hostname (see step 4 above) | Restart `cloudflared` with `--http-host-header=localhost:11434`. Verify by comparing `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:11434/v1/models` (should be `200`) against the same request with `-H "Host: <your-tunnel-domain>"` (was `403` before the fix, `200` after) |
| Intent Classification returns oddly low confidence / wrong category often | Qwen2.5-7B is smaller than Claude Haiku; structured-output quality is good but not identical | Try `qwen2.5:14b-instruct` if your Colab GPU has the VRAM (T4 is tight at 14B even quantized - A100/L4 runtimes handle it comfortably), or tighten `agents/prompts/intent_prompt.py`'s few-shot examples |
| `with_structured_output` raises a schema/tool-calling error | The model doesn't support tool calling well, or Ollama version is old | `ollama --version` should be recent (0.3+); Qwen2.5 and Llama-3.1 are confirmed to support Ollama's tool-calling emulation, which is what `agents/llm.py`'s `_OpenAICompatibleChatModel` relies on (`method="function_calling"`) |
