# 🍜 Palate

> *A Taiwan restaurant concierge in your terminal.*

Palate is a small, opinionated LLM agent that helps you find places to eat in Taiwan —
from night-market stalls in Tainan to omakase in Taipei. Ask in English, 中文, or a
mix. It uses Google Places under the hood and speaks whichever language you do.

[繁體中文說明 →](./README.zh-TW.md)

---

## Screenshot

*(Run the app to see the chat UI. Planned: add screenshot in Phase 2.)*

## Features (Phase 1)

- 💬 **Chat UI** — Streamlit chat with message history, tool-call inspector, and a
  backend switcher in the sidebar.
- 🧠 **Two LLM backends**
  - **OpenRouter** — hosted, zero setup; free-tier models like Llama 3.3 70B.
  - **Ollama** — fully local (privacy + no rate limits); default `gemma3:4b`.
- 🛠 **Two tools the agent can call**
  - `search_restaurants(query, region, min_rating, open_now, max_results)`
  - `get_restaurant_details(place_id)` → reviews, hours, phone, website, Maps link
- 🇹🇼 **Taiwan-biased** — queries are sent with `regionCode=TW` and `languageCode=zh-TW`
  so local shops surface correctly.

## Architecture

```
   ┌────────────┐   user msg    ┌───────────────┐   tools[]   ┌─────────────┐
   │ Streamlit  │ ────────────▶ │  Agent loop   │ ──────────▶ │   Backend   │
   │   (UI)     │ ◀──────────── │ (agent.py)    │ ◀────────── │ OpenRouter/ │
   └────────────┘   events      └───────┬───────┘   reply     │   Ollama    │
                                        │                     └─────────────┘
                                        │ tool_call
                                        ▼
                                ┌───────────────┐
                                │ Google Places │
                                │  API (v1)     │
                                └───────────────┘
```

The agent loop yields three event kinds — `assistant`, `tool_call`, `tool_result` —
so the UI can render tool activity live.

## Project layout

```
palate/
├── app.py                # Streamlit entry point
├── palate/
│   ├── __init__.py
│   ├── agent.py          # tool-calling loop (yields events)
│   ├── llm.py            # OpenRouter + Ollama backends behind one protocol
│   └── tools.py          # Google Places tools + OpenAI-style schemas
├── .env.example
├── pyproject.toml
└── README.md
```

## Prerequisites

- Python **3.12+**
- [`uv`](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A **Google Places API (New)** key — enable the API at
  [console.cloud.google.com](https://console.cloud.google.com/apis/library/places.googleapis.com)
- One of:
  - An [OpenRouter](https://openrouter.ai/keys) API key, **or**
  - [Ollama](https://ollama.com) running locally with a Gemma 3 model pulled

## Setup

```bash
git clone git@github.com:hsuanchenlin/palate.git
cd palate

uv sync                     # install dependencies
cp .env.example .env        # then edit .env with your keys
```

For the local Ollama path:

```bash
ollama pull gemma3:4b       # ~3 GB. Use gemma3:12b or gemma3:27b if you have the VRAM.
```

### Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GOOGLE_PLACES_API_KEY` | ✅ | — | Places API **(New)** must be enabled on the project. |
| `OPENROUTER_API_KEY` | only for hosted | — | Get one free at openrouter.ai. |
| `OPENROUTER_MODEL` | — | `meta-llama/llama-3.3-70b-instruct:free` | Must support tool calling. See below. |
| `OLLAMA_HOST` | — | `http://localhost:11434` | — |
| `OLLAMA_MODEL` | — | `gemma3:4b` | Any Ollama model with tool-call support. |

## Run

```bash
uv run streamlit run app.py
```

Open http://localhost:8501, pick a backend in the sidebar, and start chatting.

## Example prompts

- `台北大安區推薦的牛肉麵，評分 4.3 以上`
- `dumplings near Taipei 101 that are open now`
- `給我永康街那間鼎泰豐的電話跟營業時間`
- `vegan brunch in Tainan, quiet atmosphere`
- `Best ramen in Ximending — give me 3 with ratings and hours`

## Model notes

Not every OpenRouter model supports function calling. `google/gemma-3-27b-it:free`, for
example, currently does **not** — the default was switched to Llama 3.3 70B for this reason.

Free-tier models worth trying (all support tool calls):

- `meta-llama/llama-3.3-70b-instruct:free` *(default — well-rounded)*
- `google/gemma-4-26b-a4b-it:free`
- `openai/gpt-oss-120b:free`
- `qwen/qwen3-next-80b-a3b-instruct:free`
- `nvidia/nemotron-nano-9b-v2:free` *(smallest, fastest)*

OpenRouter's free tier is rate-limited per upstream provider. Palate handles this
automatically: when the selected model returns 429 or 503, the backend retries down a
built-in chain of tool-capable free models (`DEFAULT_FALLBACK_MODELS` in `palate/llm.py`)
and the UI notes which model actually answered. Pass `fallback_models=[]` to disable,
or a custom list to override. For zero rate-limits, use Ollama locally.

## Testing

```bash
uv run pytest                # unit tests (fast, no network)
uv run pytest -m live        # live integration — hits Places + OpenRouter, needs .env
uv run pytest --cov=palate   # (if you add pytest-cov)
```

There's also a streaming manual probe:

```bash
uv run python scripts/e2e.py
uv run python scripts/e2e.py "台北大安區好吃的牛肉麵"
```

```
tests/
├── test_tools.py        # pure functions + respx-mocked HTTP
├── test_agent.py        # scripted ScriptedBackend drives the loop
└── test_integration.py  # @pytest.mark.live; auto-skips if keys absent or 429
```

## Roadmap

- **Phase 1** ✅ agent loop + 2 tools + chat UI
- **Phase 2** — map view of results, favorites, sharing a shortlist
- **Phase 3** — photo understanding (menu / storefront OCR), reservation links
- **Phase 4** — trip planning across cities (route + schedule aware)

## Troubleshooting

**`Google Places PERMISSION_DENIED: Places API (New) has not been used in project ...`**
Enable *Places API (New)* (not the legacy "Places API") in Google Cloud Console, wait ~1 min
for propagation, and retry.

**`No endpoints found that support tool use`** — your chosen OpenRouter model doesn't support
function calling. Pick one from the list above.

**`temporarily rate-limited upstream` (429)** — OpenRouter free tier. Retry, switch model,
or use Ollama.

**Ollama returns empty tool calls** — Gemma 3 on older Ollama versions was flaky on tool
calls. Update Ollama (`brew upgrade ollama`) and pull the model again.

## License

MIT — do what you like, don't blame me if the noodles are soggy.
