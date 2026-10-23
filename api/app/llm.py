"""The one place the app talks to a language model.

Every call asks for JSON that validates against a Pydantic model (structured outputs), so
callers get typed objects or an exception, never free text to parse. Prompts are files in
app/prompts/ and are versioned with the code.

Providers are tried in the order of settings.llm_providers (for example "gemini,cohere").
A provider that fails is skipped for COOLDOWN_S, so one outage costs one slow request
rather than every request. When all fail, callers get LLMUnavailable or LLMTimeout, which
the HTTP layer maps to M3 and M4.
"""

import time
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import anthropic
import cohere
import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError

from app.config import settings

PROMPTS = Path(__file__).parent / "prompts"
TIMEOUT_S = 30.0
COOLDOWN_S = 120.0


class LLMUnavailable(Exception):
    """Provider down, out of credit, overloaded or rate limiting us. Shown as M3."""


class LLMTimeout(Exception):
    """No answer within TIMEOUT_S. Shown to the user as M4."""


@cache
def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema in the strict form providers accept: every $ref inlined, and
    every property required (optional ones are already nullable, so the model writes null
    rather than leaving them out)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].split("/")[-1]])
            out = {k: inline(v) for k, v in node.items() if k != "default"}
            if "properties" in out:
                out["required"] = list(out["properties"])
            return out
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return inline(schema)  # type: ignore[no-any-return]


# --- providers ------------------------------------------------------------------------
# Each takes (system prompt, user content, schema, writer) and returns raw JSON text.
# `writer` is True for the Output B answer, which may use a stronger model.

Call = Callable[[str, str, type[BaseModel], bool], str]


@cache
def _anthropic() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=TIMEOUT_S, max_retries=1)


def _call_anthropic(system: str, user: str, schema: type[BaseModel], writer: bool) -> str:
    options: dict[str, Any] = (
        {"model": settings.llm_writer_model, "output_config": {"effort": "low"}}
        if writer
        else {
            "model": settings.llm_fast_model,
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "low"},
        }
    )
    try:
        response = _anthropic().messages.parse(
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            **options,
        )
    except anthropic.APITimeoutError as exc:
        raise LLMTimeout from exc
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        # APIStatusError covers 429 and 5xx, and the 400 for an exhausted credit balance.
        raise LLMUnavailable from exc
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise LLMUnavailable(f"no parsed output (stop_reason={response.stop_reason})")
    return response.parsed_output.model_dump_json()


@cache
def _gemini() -> genai.Client:
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=genai_types.HttpOptions(timeout=int(TIMEOUT_S * 1000)),
    )


def _call_gemini(system: str, user: str, schema: type[BaseModel], writer: bool) -> str:
    try:
        response = _gemini().models.generate_content(
            model=settings.gemini_writer_model if writer else settings.gemini_fast_model,
            contents=user,
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=json_schema(schema),
            ),
        )
    except httpx.TimeoutException as exc:
        raise LLMTimeout from exc
    except (genai_errors.APIError, httpx.HTTPError) as exc:
        raise LLMUnavailable from exc
    if not response.text:
        raise LLMUnavailable("empty response")
    return response.text


@cache
def _cohere() -> cohere.ClientV2:
    return cohere.ClientV2(api_key=settings.cohere_api_key, timeout=TIMEOUT_S)


def _call_cohere(system: str, user: str, schema: type[BaseModel], writer: bool) -> str:
    try:
        response = _cohere().chat(
            model=settings.cohere_chat_model,
            messages=[
                cohere.SystemChatMessageV2(content=system),
                cohere.UserChatMessageV2(content=user),
            ],
            response_format=cohere.JsonObjectResponseFormatV2(json_schema=json_schema(schema)),
            temperature=0,
        )
    except httpx.TimeoutException as exc:
        raise LLMTimeout from exc
    except (cohere.core.ApiError, httpx.HTTPError) as exc:
        raise LLMUnavailable from exc
    text = "".join(getattr(part, "text", "") for part in response.message.content or [])
    if not text:
        raise LLMUnavailable("empty response")
    return text


_PROVIDERS: dict[str, tuple[Call, Callable[[], bool]]] = {
    "anthropic": (_call_anthropic, lambda: bool(settings.anthropic_api_key)),
    "gemini": (_call_gemini, lambda: bool(settings.gemini_api_key)),
    "cohere": (_call_cohere, lambda: bool(settings.cohere_api_key)),
}
_cooling_until: dict[str, float] = {}


def configured_providers() -> list[str]:
    names = [n.strip() for n in settings.llm_providers.split(",")]
    return [n for n in names if n in _PROVIDERS and _PROVIDERS[n][1]()]


def provider_health() -> dict[str, str]:
    """For /api/health: each configured provider, and whether it is cooling down."""
    now = time.monotonic()
    return {
        name: "cooling down" if _cooling_until.get(name, 0) > now else "ready"
        for name in configured_providers()
    }


def structured[T: BaseModel](
    prompt_name: str, user_content: str, schema: type[T], *, writer: bool = False
) -> T:
    """`writer=True` for Output B prose; everything else is classification or extraction."""
    names = configured_providers()
    now = time.monotonic()
    # Healthy providers first, in configured order; cooling ones only as a last resort.
    order = [n for n in names if _cooling_until.get(n, 0) <= now]
    order += [n for n in names if n not in order]
    last: Exception = LLMUnavailable("no language model provider configured")
    for name in order:
        call, _ = _PROVIDERS[name]
        try:
            return schema.model_validate_json(
                call(prompt(prompt_name), user_content, schema, writer)
            )
        except (LLMUnavailable, LLMTimeout, ValidationError) as exc:
            _cooling_until[name] = time.monotonic() + COOLDOWN_S
            last = exc
    if isinstance(last, LLMTimeout):
        raise last
    raise LLMUnavailable(repr(last)) from last
