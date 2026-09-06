import json
from typing import Any

from app.autonomy import ACTIONS, LEVELS
from app.config import settings

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "autonomy_level": {"type": "string", "enum": list(LEVELS)},
        "confidence": {"type": "number"},
        "action_type": {"type": "string", "enum": list(ACTIONS)},
        "reasoning": {"type": "string"},
        "draft": {"type": ["string", "null"]},
        "label": {"type": ["string", "null"]},
    },
    "required": [
        "autonomy_level",
        "confidence",
        "action_type",
        "reasoning",
        "draft",
        "label",
    ],
}

SAFETY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "money": {"type": "string", "enum": ["none", "ask_first", "escalate"]},
        "prompt_injection": {"type": "string", "enum": ["none", "ask_first", "escalate"]},
        "reason": {"type": "string"},
    },
    "required": ["money", "prompt_injection", "reason"],
}


class LlmUnavailable(RuntimeError):
    pass


def llm_configured() -> bool:
    return bool(settings.openai_api_key or settings.anthropic_api_key)


def complete_decision(system: str, user: str) -> dict[str, Any]:
    return complete_json(system, user, DECISION_SCHEMA, "autonomy_decision")


def complete_json(system: str, user: str, schema: dict[str, Any], name: str) -> dict[str, Any]:
    provider = (settings.llm_provider or "openai").lower()
    if provider == "anthropic" and settings.anthropic_api_key:
        return _anthropic(system, user, schema, name)
    if provider == "openai" and settings.openai_api_key:
        return _openai(system, user, schema, name)
    if settings.openai_api_key:
        return _openai(system, user, schema, name)
    if settings.anthropic_api_key:
        return _anthropic(system, user, schema, name)
    raise LlmUnavailable("no LLM key in env")


def _openai(system: str, user: str, schema: dict[str, Any], name: str) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": True,
                "schema": schema,
            },
        },
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


def _anthropic(system: str, user: str, schema: dict[str, Any], name: str) -> dict[str, Any]:
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=800,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[
            {
                "name": name,
                "description": "Record the structured result.",
                "input_schema": schema,
            }
        ],
        tool_choice={"type": "tool", "name": name},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == name:
            return dict(block.input)
    raise RuntimeError("anthropic did not return a structured tool call")
