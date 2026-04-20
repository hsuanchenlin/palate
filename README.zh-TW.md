# 🍜 Palate

> *口袋裡的台灣餐廳小幫手。*

Palate 是一個小而專注的 LLM 代理，協助你在台灣找餐廳 —— 從台南的夜市小吃、到
台北的無菜單料理都能問。用中文、英文、或中英混著問都可以，它會照著你的語言回。
底層使用 Google Places API 抓資料。

[English README →](./README.md)

---

## 畫面預覽

*（執行後可以看到聊天介面。Phase 2 會補上截圖。）*

## 功能（Phase 1）

- 💬 **聊天介面** —— Streamlit 聊天 UI，包含對話紀錄、工具呼叫檢視器、以及
  側欄的後端切換器。
- 🧠 **兩種 LLM 後端**
  - **OpenRouter**（雲端）—— 幾乎零設定，免費模型可選 Llama 3.3 70B 等。
  - **Ollama**（本機）—— 完全離線（隱私 + 無 rate limit），預設 `gemma3:4b`。
- 🛠 **代理可以呼叫的兩個工具**
  - `search_restaurants(query, region, min_rating, open_now, max_results)`
  - `get_restaurant_details(place_id)` → 評論、營業時間、電話、網站、Google Maps 連結
- 🇹🇼 **台灣在地優化** —— 查詢時帶 `regionCode=TW` 與 `languageCode=zh-TW`，
  在地小店才搜得到。

## 架構圖

```
   ┌────────────┐   使用者訊息  ┌───────────────┐   tools[]   ┌─────────────┐
   │ Streamlit  │ ────────────▶ │  Agent 迴圈   │ ──────────▶ │   後端       │
   │   (UI)     │ ◀──────────── │ (agent.py)    │ ◀────────── │ OpenRouter/ │
   └────────────┘   事件流       └───────┬───────┘   回覆      │   Ollama    │
                                        │                     └─────────────┘
                                        │ tool_call
                                        ▼
                                ┌───────────────┐
                                │ Google Places │
                                │  API (v1)     │
                                └───────────────┘
```

Agent 迴圈會產生三種事件 —— `assistant`、`tool_call`、`tool_result`，UI 可以
即時顯示工具的執行狀況。

## 專案結構

```
palate/
├── app.py                # Streamlit 入口
├── palate/
│   ├── __init__.py
│   ├── agent.py          # Tool-calling 迴圈（用 generator 產出事件）
│   ├── llm.py            # OpenRouter + Ollama 後端（共用 Backend protocol）
│   └── tools.py          # Google Places 工具 + OpenAI 格式的 schema
├── .env.example
├── pyproject.toml
└── README.zh-TW.md
```

## 環境需求

- Python **3.12+**
- [`uv`](https://docs.astral.sh/uv/) —— 安裝：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- 一把 **Google Places API (New)** 金鑰 —— 在
  [console.cloud.google.com](https://console.cloud.google.com/apis/library/places.googleapis.com)
  啟用「Places API (New)」。
- 擇一：
  - [OpenRouter](https://openrouter.ai/keys) API key，或
  - 本機跑 [Ollama](https://ollama.com) 並下載一個 Gemma 3 模型

## 安裝

```bash
git clone git@github.com:hsuanchenlin/palate.git
cd palate

uv sync                     # 安裝套件
cp .env.example .env        # 然後把你的金鑰填進 .env
```

本機 Ollama 模式：

```bash
ollama pull gemma3:4b       # 約 3 GB；VRAM 夠的話可以試 gemma3:12b 或 gemma3:27b
```

### 環境變數

| 變數 | 是否必填 | 預設值 | 備註 |
|---|---|---|---|
| `GOOGLE_PLACES_API_KEY` | ✅ | — | 專案要先啟用 **Places API (New)**。 |
| `OPENROUTER_API_KEY` | 用雲端才需要 | — | 在 openrouter.ai 免費註冊。 |
| `OPENROUTER_MODEL` | — | `meta-llama/llama-3.3-70b-instruct:free` | 必須支援 tool calling，下面有說明。 |
| `OLLAMA_HOST` | — | `http://localhost:11434` | — |
| `OLLAMA_MODEL` | — | `gemma3:4b` | 任何支援 tool-call 的 Ollama 模型。 |

## 執行

```bash
uv run streamlit run app.py
```

打開 http://localhost:8501，在側欄選擇後端、開始聊天。

## 範例提問

- `台北大安區推薦的牛肉麵，評分 4.3 以上`
- `dumplings near Taipei 101 that are open now`
- `給我永康街那間鼎泰豐的電話跟營業時間`
- `台南適合素食早午餐、氣氛安靜的地方`
- `西門町最好吃的拉麵三間，附評分和營業時間`

## 模型小提醒

不是每個 OpenRouter 模型都支援 function calling。例如 `google/gemma-3-27b-it:free`
目前就**不支援** —— 所以預設改成了 Llama 3.3 70B。

其他支援工具呼叫的免費模型：

- `meta-llama/llama-3.3-70b-instruct:free` *（預設，綜合表現穩）*
- `google/gemma-4-26b-a4b-it:free`
- `openai/gpt-oss-120b:free`
- `qwen/qwen3-next-80b-a3b-instruct:free`
- `nvidia/nemotron-nano-9b-v2:free` *（最小、最快）*

OpenRouter 免費版會被上游供應商限速。Palate 會自動處理：選定的模型若回 429 或 503，
後端會沿著內建的 tool-call 相容免費模型清單（`palate/llm.py` 裡的 `DEFAULT_FALLBACK_MODELS`）
逐一 retry，UI 會顯示實際回答的是哪個模型。傳 `fallback_models=[]` 可以關掉，或自訂
清單。想要零限速，就用本機 Ollama。

## 快取

Google Places 的回應會快取到本機 SQLite 檔，省 API 額度也讓重複查詢幾乎是瞬間回應。

- **位置：** `~/.cache/palate/places.sqlite3`（可用 `PALATE_CACHE_DIR` 覆蓋）
- **TTL：** `search_restaurants` 24 小時、`get_restaurant_details` 7 天
- **停用：** 設定 `PALATE_DISABLE_CACHE=1`
- **清除：** Streamlit 側欄的 Clear cache 按鈕，或 `rm -rf ~/.cache/palate`

測試時 `tests/conftest.py` 會自動把快取設成 disabled，讓 respx mock 的 HTTP 路徑仍會實際執行。

## 測試

```bash
uv run pytest                # 單元測試（快速，不連網路）
uv run pytest -m live        # 實際連 Places + OpenRouter，需要 .env
uv run pytest --cov=palate   # 搭配 pytest-cov 可看覆蓋率
```

另外有一個手動串流測試腳本：

```bash
uv run python scripts/e2e.py
uv run python scripts/e2e.py "台北大安區好吃的牛肉麵"
```

```
tests/
├── test_tools.py        # 純函式 + respx mock HTTP
├── test_agent.py        # ScriptedBackend 驅動 agent 迴圈
└── test_integration.py  # @pytest.mark.live；金鑰沒設或 429 時自動 skip
```

## Roadmap

- **Phase 1** ✅ Agent 迴圈 + 2 個工具 + 聊天 UI
- **Phase 2** —— 結果的地圖檢視、我的最愛、分享清單
- **Phase 3** —— 照片理解（菜單 / 店面 OCR）、訂位連結
- **Phase 4** —— 跨縣市行程規劃（考慮路線與時段）

## 疑難排解

**`Google Places PERMISSION_DENIED: Places API (New) has not been used in project ...`**
請到 Google Cloud Console 啟用「Places API (New)」（不是舊的「Places API」），等約一分鐘
讓設定生效，再重試。

**`No endpoints found that support tool use`** —— 選到的 OpenRouter 模型不支援函式呼叫。
從上面清單挑一個。

**`temporarily rate-limited upstream`（429）** —— OpenRouter 免費版限速。重試、換模型、
或改用 Ollama。

**Ollama 回傳空的 tool_calls** —— 舊版 Ollama 跑 Gemma 3 的 tool-call 會不穩。
請更新 Ollama（`brew upgrade ollama`）並重新 pull 模型。

## 授權

MIT —— 想怎麼用都行，麵煮爛了別怪我。
