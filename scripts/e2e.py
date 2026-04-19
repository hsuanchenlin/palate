"""Manual end-to-end probe — one agent turn against the real APIs.

Unlike the pytest suite, this script streams events to stdout so you can watch
the agent think/call/answer in real time. Useful when swapping models or
debugging a broken response.

Usage:
    uv run python scripts/e2e.py
    uv run python scripts/e2e.py "台北大安區好吃的牛肉麵"
    OPENROUTER_MODEL=google/gemma-4-26b-a4b-it:free uv run python scripts/e2e.py
"""

import os
import sys
from pathlib import Path

# Make the project root importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from palate.agent import Agent
from palate.llm import OpenRouterBackend

load_dotenv()

MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
PROMPT = sys.argv[1] if len(sys.argv) > 1 else (
    "Recommend 2 highly-rated beef noodle places in Da-an district, Taipei. Include ratings."
)


def main() -> int:
    if not os.environ.get("GOOGLE_PLACES_API_KEY"):
        print("✗ GOOGLE_PLACES_API_KEY not set. Put it in .env first.")
        return 2
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("✗ OPENROUTER_API_KEY not set. Put it in .env first.")
        return 2

    print(f"model:  {MODEL}")
    print(f"prompt: {PROMPT}")
    print("-" * 60)

    agent = Agent(backend=OpenRouterBackend(model=MODEL))
    messages = [{"role": "user", "content": PROMPT}]

    for ev in agent.run(messages):
        if ev.kind == "tool_call":
            print(f">> CALL {ev.data['name']}({ev.data['arguments']})")
        elif ev.kind == "tool_result":
            r = ev.data["result"]
            if isinstance(r, dict) and "results" in r:
                print(f"<< {len(r['results'])} place(s)")
            elif isinstance(r, dict) and "error" in r:
                print(f"<< ERROR: {r['error']}")
            else:
                keys = list(r.keys())[:6] if isinstance(r, dict) else type(r).__name__
                print(f"<< keys: {keys}")
        elif ev.kind == "assistant":
            if ev.data.content and not ev.data.tool_calls:
                print("-" * 60)
                print("FINAL ANSWER:")
                print(ev.data.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
