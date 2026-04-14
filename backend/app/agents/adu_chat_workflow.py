from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from agent_framework.openai import OpenAIChatClient
from agent_framework.orchestrations import SequentialBuilder

logger = logging.getLogger("adu_backend.agents.chat")

CHAT_AGENT_LOG_VERBOSE = os.getenv("CHAT_AGENT_LOG_VERBOSE", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CHAT_AGENT_LOG_MAX_CHARS = int(os.getenv("CHAT_AGENT_LOG_MAX_CHARS", "1200"))
CHAT_AGENT_ENFORCE_NUMERIC_GUARDRAIL = os.getenv("CHAT_AGENT_ENFORCE_NUMERIC_GUARDRAIL", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CHAT_AGENT_NUMERIC_GUARDRAIL_MODE = os.getenv("CHAT_AGENT_NUMERIC_GUARDRAIL_MODE", "").strip().lower()
if CHAT_AGENT_NUMERIC_GUARDRAIL_MODE not in {"off", "warn", "strict"}:
    CHAT_AGENT_NUMERIC_GUARDRAIL_MODE = "strict" if CHAT_AGENT_ENFORCE_NUMERIC_GUARDRAIL else "off"
CHAT_AGENT_ENABLE_REVIEWER = os.getenv("CHAT_AGENT_ENABLE_REVIEWER", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _build_chat_client() -> OpenAIChatClient:
    base_url = os.getenv("OPENAI_API_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    model_id = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for Agent Framework chat workflow")

    return OpenAIChatClient(
        model_id=model_id,
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


def _truncate_for_log(text: str, max_chars: int = CHAT_AGENT_LOG_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated {len(text) - max_chars} chars]"


def _summarize_outputs(outputs: list[Any]) -> list[str]:
    summary: list[str] = []
    for index, item in enumerate(outputs):
        if isinstance(item, list):
            extracted = _extract_output_text([item]) or ""
            summary.append(
                f"step={index} type=list messages={len(item)} text={_truncate_for_log(extracted)}"
            )
        else:
            summary.append(
                f"step={index} type={type(item).__name__} value={_truncate_for_log(str(item))}"
            )
    return summary


def _extract_all_output_text(outputs: list[Any]) -> str:
    lines: list[str] = []
    for item in outputs:
        if isinstance(item, list):
            for message in item:
                for attr in ("content", "text"):
                    value = getattr(message, attr, None)
                    if value:
                        lines.append(str(value))
                        break
        elif isinstance(item, str):
            lines.append(item)
        else:
            lines.append(str(item))
    return "\n".join(lines)


def _extract_numeric_tokens(text: str) -> set[str]:
    raw = re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", text or "")
    return {token.replace(",", "") for token in raw}


def _find_unsupported_numeric_claims(answer_text: str, evidence_text: str) -> list[str]:
    answer_numbers = _extract_numeric_tokens(answer_text)
    evidence_numbers = _extract_numeric_tokens(evidence_text)
    unsupported = sorted(number for number in answer_numbers if number not in evidence_numbers)
    return unsupported


def _guardrailed_uncertainty_response(unsupported_numbers: list[str]) -> str:
    unsupported_text = ", ".join(unsupported_numbers[:8])
    return (
        "Answer:\n"
        "- I can’t confidently provide numeric thresholds from the currently retrieved evidence.\n"
        "Reasoning:\n"
        "1. Handbook baseline rule: The relevant topic appears in context but the exact numeric threshold is not clearly grounded.\n"
        "2. Bill updates applied: No confirmed override with explicit numbers was validated from retrieved evidence.\n"
        "3. Conflict resolution used: No conflict resolved because numeric support is insufficient.\n"
        "4. Project-specific assumptions/limits: Numeric claims require explicit citation.\n"
        "Related information:\n"
        "- Primary source: Retrieved ADU handbook/bill context (insufficient numeric specificity).\n"
        f"- Applied updates: Not applied due to unsupported numeric claims ({unsupported_text}).\n"
        "- Important assumptions/limits: Numeric claims require explicit citation.\n"
        "Possible next step:\n"
        "1. Retrieve the specific SB/GC section text for this numeric threshold and re-run.\n"
        "2. Confirm the cited section language before final compliance guidance."
    )


def _append_numeric_verification_note(response_text: str, unsupported_numbers: list[str]) -> str:
    unsupported_text = ", ".join(unsupported_numbers[:8])
    note = (
        "\n\nRelated information:\n"
        f"- Verification note: Numeric claims requiring confirmation from retrieved evidence: {unsupported_text}.\n"
        "- Important assumptions/limits: Verify the exact statutory text/citation before final compliance determination."
    )
    return f"{response_text}{note}"


def build_adu_chat_workflow():
    client = _build_chat_client()

    context_curator = client.as_agent(
        name="adu_context_curator",
        instructions=(
            "You will receive ADU regulation context, conversation summary, and a user question. "
            "Extract only the most relevant handbook/bill facts needed to answer the question. "
            "Return structured evidence in this format:\n"
            "FACTS (handbook baseline):\n- ...\n"
            "BILL_UPDATES (overrides/deltas):\n- ...\n"
            "CONFLICT_RESOLUTION:\n- ...\n"
            "MISSING_INFO:\n- ...\n"
            "MANDATORY_CHECKS:\n"
            "- Identify every explicit sub-question in the user request and collect evidence for each.\n"
            "- If a numeric scenario is provided by the user, capture all provided numbers exactly.\n"
            "- Include nearby constraints/allowances that materially change practical interpretation when present in evidence.\n"
            "Keep each bullet specific and source-grounded (version/date/bill id when available). "
            "Do not answer the question yet."
        ),
    )

    answer_agent = client.as_agent(
        name="adu_answer_agent",
        instructions=(
            "Use the curated evidence from prior agent output to answer the ADU question. "
            "Use this preferred response structure (adapt if needed for clarity/completeness):\n"
            "Answer:\n- ...\n"
            "Reasoning:\n"
            "1. Handbook baseline rule: ...\n"
            "2. Bill updates applied: ...\n"
            "3. Conflict resolution used: ...\n"
            "4. Project-specific assumptions/limits: ...\n"
            "Related information:\n"
            "- Primary unit(s): ...\n"
            "- ADU allowance: ...\n"
            "- JADU allowance: ...\n"
            "- Primary source: ...\n"
            "- Applied updates: ...\n"
            "Possible next step:\n"
            "- Given input: ...\n"
            "- Step-by-step check: ...\n"
            "- Conclusion for this scenario: ...\n"
            "Provide moderate depth and complete the user ask in full; do not stop at a minimal one-line answer. "
            "Do not omit materially relevant allowances or constraints when directly supported by evidence. "
            "For Primary source and Applied updates, include direct source URLs and page numbers when available in evidence. "
            "If uncertain, include one brief uncertainty sentence under Answer."
        ),
    )

    answer_reviewer = client.as_agent(
        name="adu_answer_reviewer",
        instructions=(
            "Review and improve the draft answer for completeness, groundedness, and clarity. "
            "Your tasks:\n"
            "1) Ensure all explicit user sub-questions are answered.\n"
            "2) Preserve user-provided numeric scenario inputs exactly; do not mutate given values.\n"
            "3) Add materially relevant related information from provided evidence (constraints/allowances), without introducing unsupported claims.\n"
            "4) Keep concise but not minimal; include practical next step.\n"
            "5) If any claim lacks support in evidence, mark it as uncertainty rather than asserting it.\n"
            "6) Ensure source traceability includes direct URL links and page numbers when available from evidence.\n"
            "Return only the final response in this structure:\n"
            "Answer:\n- ...\n"
            "Reasoning:\n1. ...\n2. ...\n"
            "Related information:\n- ...\n"
            "Possible next step:\n1. ..."
        ),
    )
    participants = [context_curator, answer_agent]
    if CHAT_AGENT_ENABLE_REVIEWER:
        participants.append(answer_reviewer)

    return SequentialBuilder(participants=participants).build()


async def run_adu_chat_workflow(
    *,
    system_prompt: str,
    context_header: str,
    context_text: str,
    conversation_text: str,
    query_text: str,
    trace_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    trace = trace_id or "n/a"

    logger.info(
        "agent_chat trace=%s start query_chars=%d context_chars=%d conversation_chars=%d",
        trace,
        len(query_text or ""),
        len(context_text or ""),
        len(conversation_text or ""),
    )

    workflow = build_adu_chat_workflow()

    workflow_input = (
        f"SYSTEM PROMPT:\n{system_prompt}\n\n"
        f"{context_header}:\n{context_text}\n\n"
        f"RECENT CONVERSATION:\n{conversation_text or '(none)'}\n\n"
        f"USER QUESTION:\n{query_text}"
    )

    events = await workflow.run(workflow_input)
    outputs = events.get_outputs()

    if CHAT_AGENT_LOG_VERBOSE:
        for line in _summarize_outputs(outputs):
            logger.info("agent_chat trace=%s %s", trace, line)

    response_text = _extract_output_text(outputs)

    if CHAT_AGENT_NUMERIC_GUARDRAIL_MODE != "off" and response_text:
        evidence_text = f"{system_prompt}\n{context_text}\n{_extract_all_output_text(outputs)}"
        unsupported_numbers = _find_unsupported_numeric_claims(response_text, evidence_text)
        if unsupported_numbers:
            logger.warning(
                "agent_chat trace=%s numeric_guardrail mode=%s unsupported_numbers=%s",
                trace,
                CHAT_AGENT_NUMERIC_GUARDRAIL_MODE,
                ",".join(unsupported_numbers),
            )
            if CHAT_AGENT_NUMERIC_GUARDRAIL_MODE == "strict":
                response_text = _guardrailed_uncertainty_response(unsupported_numbers)
            else:
                response_text = _append_numeric_verification_note(response_text, unsupported_numbers)

    logger.info(
        "agent_chat trace=%s done duration_ms=%.1f response_chars=%d",
        trace,
        (time.perf_counter() - started) * 1000,
        len(response_text or ""),
    )

    if CHAT_AGENT_LOG_VERBOSE and response_text:
        logger.info("agent_chat trace=%s response_preview=%s", trace, _truncate_for_log(response_text))

    return {
        "status": "ok",
        "response_text": response_text or "",
    }
