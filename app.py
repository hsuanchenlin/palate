import json
import os

import streamlit as st
from dotenv import load_dotenv

from palate.agent import Agent
from palate.llm import OllamaBackend, OpenRouterBackend, available_ollama_models

load_dotenv()

st.set_page_config(page_title="Palate — Taiwan restaurants", page_icon="🍜", layout="centered")
st.title("🍜 Palate")
st.caption("Taiwan restaurant concierge — ask in English or 中文")

with st.sidebar:
    st.header("Backend")
    backend_choice = st.radio("LLM", ["OpenRouter", "Ollama"], index=0)

    if backend_choice == "OpenRouter":
        default_model = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        model = st.text_input("Model", value=default_model)
        api_key_set = bool(os.environ.get("OPENROUTER_API_KEY"))
        st.caption("OPENROUTER_API_KEY: " + ("✅ set" if api_key_set else "❌ missing — set in .env"))
    else:
        default_model = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
        local_models = list(available_ollama_models())
        if local_models:
            model = st.selectbox(
                "Model",
                local_models,
                index=local_models.index(default_model) if default_model in local_models else 0,
            )
        else:
            model = st.text_input("Model", value=default_model)
            st.caption("Could not list local models. Is Ollama running?")

    places_key_set = bool(os.environ.get("GOOGLE_PLACES_API_KEY"))
    st.caption("GOOGLE_PLACES_API_KEY: " + ("✅ set" if places_key_set else "❌ missing — set in .env"))

    if st.button("Reset conversation", use_container_width=True):
        st.session_state.pop("messages", None)
        st.rerun()


if "messages" not in st.session_state:
    st.session_state.messages = []


def render_history():
    for m in st.session_state.messages:
        role = m["role"]
        if role == "system":
            continue
        if role == "tool":
            with st.chat_message("assistant"):
                with st.expander(f"🔧 {m.get('name', 'tool')} result", expanded=False):
                    try:
                        st.json(json.loads(m["content"]))
                    except Exception:
                        st.code(m["content"])
            continue
        if role == "assistant" and m.get("tool_calls"):
            with st.chat_message("assistant"):
                if m.get("content"):
                    st.markdown(m["content"])
                for tc in m["tool_calls"]:
                    fn = tc["function"]
                    with st.expander(f"🛠 call `{fn['name']}`", expanded=False):
                        try:
                            st.json(json.loads(fn["arguments"]))
                        except Exception:
                            st.code(fn["arguments"])
            continue
        with st.chat_message(role):
            st.markdown(m.get("content", ""))


render_history()

prompt = st.chat_input("e.g. 台北大安區好吃的牛肉麵, or: dumplings near Taipei 101")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        if backend_choice == "OpenRouter":
            backend = OpenRouterBackend(model=model)
        else:
            backend = OllamaBackend(model=model)
    except Exception as e:
        st.error(f"Backend init failed: {e}")
        st.stop()

    agent = Agent(backend=backend)

    with st.spinner(f"thinking with {backend.name}:{model}…"):
        try:
            for event in agent.run(st.session_state.messages):
                if event.kind == "tool_call":
                    tc = event.data
                    with st.chat_message("assistant"):
                        with st.expander(f"🛠 calling `{tc['name']}`", expanded=True):
                            st.json(tc["arguments"])
                elif event.kind == "tool_result":
                    with st.chat_message("assistant"):
                        with st.expander(f"🔧 `{event.data['name']}` result", expanded=False):
                            st.json(event.data["result"])
                elif event.kind == "assistant":
                    msg = event.data
                    if msg.content and not msg.tool_calls:
                        with st.chat_message("assistant"):
                            st.markdown(msg.content)
                            actual = getattr(backend, "last_used_model", None)
                            if actual and actual != model:
                                st.caption(f"⚠️ {model} was rate-limited; answered with `{actual}`")
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate-limited" in msg.lower():
                st.error(
                    f"All fallback models are rate-limited right now. "
                    f"Try again in a minute, switch to Ollama, or add a paid OpenRouter key.\n\n{type(e).__name__}: {msg}"
                )
            else:
                st.error(f"Agent error: {type(e).__name__}: {e}")
