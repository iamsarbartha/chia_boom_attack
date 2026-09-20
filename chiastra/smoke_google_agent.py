"""Test Google ADK independently of Chia and Ray.

Examples: python smoke_google_agent.py, --parallel 2, or --agent research.
Parallel probes are opt-in because they can trigger 429s.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from google_agent import GlobalGemini, vulnerability_research_agent_2


async def run_agent(agent: Any, prompt: str, app_name: str) -> str:
    runner = InMemoryRunner(app=App(name=app_name, root_agent=agent))
    session = await runner.session_service.create_session(
        app_name=app_name, user_id="chiastra_smoke_test"
    )
    message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    final_text = ""
    async for event in runner.run_async(
        user_id="chiastra_smoke_test", session_id=session.id, new_message=message
    ):
        if getattr(event, "author", None) != agent.name:
            continue
        parts = getattr(getattr(event, "content", None), "parts", None) or []
        text = "".join(getattr(part, "text", "") or "" for part in parts)
        if text:
            final_text = text
    if not final_text:
        raise RuntimeError(f"{agent.name} returned no text")
    return final_text


async def probe(index: int, model: str, timeout: float) -> tuple[bool, str]:
    agent = LlmAgent(
        name=f"connection_probe_{index}",
        model=GlobalGemini(model=model),
        instruction="Reply briefly. Do not use tools or delegate to other agents.",
    )
    try:
        response = await asyncio.wait_for(
            run_agent(agent, "Reply with the exact token ADK_OK.",
                      f"chiastra_adk_probe_{index}"),
            timeout=timeout,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if "ADK_OK" not in response:
        return False, f"Unexpected response: {response[:500]}"
    return True, response[:500]


async def research_probe(timeout: float) -> tuple[bool, str]:
    try:
        response = await asyncio.wait_for(
            run_agent(
                vulnerability_research_agent_2,
                "Give a brief, sourced example of a cache side-channel that "
                "could be studied on RISC-V BOOM. Do not run hardware tools.",
                "chiastra_adk_research_probe",
            ),
            timeout=timeout,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, response[:1000]


async def run_probes(count: int, model: str, timeout: float) -> list[tuple[bool, str]]:
    return await asyncio.gather(*(
        probe(index, model, timeout) for index in range(1, count + 1)
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent", choices=("probe", "research"), default="probe",
        help="probe tests connectivity; research runs the real ADK research agent",
    )
    parser.add_argument(
        "--parallel", type=int, default=1, metavar="N",
        help="simultaneous connectivity probes (1-4; default: 1)",
    )
    parser.add_argument(
        "--model", default=None,
        help="probe model (default: CHIASTRA_GEMINI_MODEL or gemini-3.5-flash)",
    )
    parser.add_argument(
        "--timeout", type=float, default=600,
        help="per-probe timeout in seconds, including SDK retries (default: 600)",
    )
    args = parser.parse_args()
    if not 1 <= args.parallel <= 4:
        parser.error("--parallel must be between 1 and 4")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.agent == "research" and (args.parallel != 1 or args.model):
        parser.error("--agent research does not support --parallel or --model")
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        parser.error("set GOOGLE_CLOUD_PROJECT before running the test")

    model = args.model or os.environ.get("CHIASTRA_GEMINI_MODEL", "gemini-3.5-flash")
    model_label = model if args.agent == "probe" else "configured research model"
    print(f"ADK test: agent={args.agent}, project={os.environ['GOOGLE_CLOUD_PROJECT']}, "
          f"model={model_label}, parallel={args.parallel}", flush=True)

    if args.agent == "research":
        results = [asyncio.run(research_probe(args.timeout))]
    else:
        results = asyncio.run(run_probes(args.parallel, model, args.timeout))
    for index, (ok, detail) in enumerate(results, start=1):
        print(f"Probe {index}: {'PASS' if ok else 'FAIL'}: {detail}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

