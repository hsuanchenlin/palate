# 🍜 Palate

Taiwan restaurant concierge — an LLM agent that searches Google Places and chats about where to eat.

- **LLM**: OpenRouter (hosted) or Ollama Gemma 3 (local)
- **Data**: Google Places API (New)
- **UI**: Streamlit chat
- **Runtime**: Python 3.12 + uv

## Phase 1 scope

- Agent loop with tool calling
- Two tools: `search_restaurants`, `get_restaurant_details`
- Streamlit chat UI with backend / model switcher

## Setup

```bash
uv sync
cp .env.example .env
# fill in GOOGLE_PLACES_API_KEY and OPENROUTER_API_KEY (or pull an Ollama model)
```

For Ollama:

```bash
ollama pull gemma3:4b   # or gemma3:12b / gemma3:27b if you have the VRAM
```

## Run

```bash
uv run streamlit run app.py
```

## Notes on the default OpenRouter model

`google/gemma-3-27b-it:free` does **not** support tool calling on OpenRouter, so the default
is `meta-llama/llama-3.3-70b-instruct:free`. Other tool-capable `:free` options: `google/gemma-4-26b-a4b-it:free`,
`openai/gpt-oss-120b:free`, `qwen/qwen3-next-80b-a3b-instruct:free`, `nvidia/nemotron-nano-9b-v2:free`.
Free-tier providers are often rate-limited; retry or swap models. For reliability, use the Ollama backend.

## Example prompts

- `台北大安區推薦的牛肉麵，評分 4.3 以上`
- `dumplings near Taipei 101 that are open now`
- `給我永康街那間鼎泰豐的電話跟營業時間`

## Project layout

```
palate/
├── app.py              # Streamlit entry
├── palate/
│   ├── agent.py        # tool-calling loop
│   ├── llm.py          # OpenRouter + Ollama backends
│   └── tools.py        # Google Places tools + schemas
├── .env.example
└── pyproject.toml
```
