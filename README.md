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
