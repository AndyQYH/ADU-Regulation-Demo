from __future__ import annotations

import json
import logging
import os
import inspect
from typing import Any, Awaitable, Callable

from agent_framework import tool
from agent_framework.openai import OpenAIChatClient
from agent_framework.orchestrations import SequentialBuilder

logger = logging.getLogger("adu_backend.agents")

RunIngestFn = Callable[[str, int], Awaitable[dict[str, Any]]]


def _build_chat_client() -> OpenAIChatClient:
    base_url = os.getenv("OPENAI_API_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    model_id = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for Agent Framework")

    constructor_params = inspect.signature(OpenAIChatClient.__init__).parameters
    model_kwarg = "model_id" if "model_id" in constructor_params else "model"

    return OpenAIChatClient(
        **{model_kwarg: model_id},
        api_key=api_key,
        base_url=base_url,
    )


def _extract_output_text(outputs: list[Any]) -> str | None:
    if not outputs:
        return None

    last = outputs[-1]
    if isinstance(last, list) and last:
        message = last[-1]
        for attr in ("content", "text"):
            value = getattr(message, attr, None)
            if value:
                return value
        return str(message)

    if isinstance(last, str):
        return last

    return str(last)


def build_regulation_workflow(run_ingest: RunIngestFn):
    client = _build_chat_client()

    @tool
    async def run_leginfo_sync(search_url: str, max_bills: int = 50) -> str:
        """Run LegInfo bill search ingest and return JSON summary."""
        result = await run_ingest(search_url, max_bills)
        return json.dumps(result, ensure_ascii=True)

    tracker = client.as_agent(
        name="regulation_tracker",
        instructions=(
            "Extract search_url and max_bills from the user input. "
            "Respond with exactly one line: 'SYNC_REQUEST search_url=<url> max_bills=<n>'. "
            "If any value is missing, ask a single short question."
        ),
    )

    ingest = client.as_agent(
        name="regulation_ingest",
        instructions=(
            "If the prior message starts with SYNC_REQUEST, parse search_url and max_bills, "
            "call run_leginfo_sync(search_url, max_bills), then respond with JSON that has keys: "
            "sync_result and notes. sync_result must be parsed JSON from the tool." 
            "If the prior message is a question, answer it briefly without calling tools."
        ),
        tools=[run_leginfo_sync],
    )

    return SequentialBuilder(participants=[tracker, ingest]).build()


async def run_regulation_workflow(
    run_ingest: RunIngestFn,
    search_url: str,
    max_bills: int,
) -> dict[str, Any]:
    workflow = build_regulation_workflow(run_ingest)
    input_text = f"search_url: {search_url}\nmax_bills: {max_bills}"

    events = await workflow.run(input_text)
    outputs = events.get_outputs()
    response_text = _extract_output_text(outputs)

    payload: dict[str, Any] = {"status": "ok", "raw_text": response_text}
    if response_text:
        try:
            payload["result"] = json.loads(response_text)
        except json.JSONDecodeError:
            payload["result"] = None
            logger.info("Workflow response was not JSON")

    return payload
