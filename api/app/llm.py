"""The one place the app talks to a language model.

Every call asks for JSON that validates against a Pydantic model (structured outputs), so
callers get typed objects or an exception, never free text to parse. Prompts are files in
app/prompts/ and are versioned with the code.

API failures are translated into two exceptions that the HTTP layer maps to M3 and M4.
"""

from functools import cache
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel

from app.config import settings

PROMPTS = Path(__file__).parent / "prompts"
TIMEOUT_S = 30.0


class LLMUnavailable(Exception):
    """Provider down, overloaded or rate limiting us. Shown to the user as M3."""


class LLMTimeout(Exception):
    """No answer within TIMEOUT_S. Shown to the user as M4."""


@cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=TIMEOUT_S, max_retries=1)


@cache
def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def structured[T: BaseModel](
    prompt_name: str, user_content: str, schema: type[T], *, writer: bool = False
) -> T:
    """`writer=True` for Output B prose; everything else is classification or extraction
    against a fixed schema and runs on the fast model with thinking off."""
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
        response = _client().messages.parse(
            max_tokens=4000,
            system=prompt(prompt_name),
            messages=[{"role": "user", "content": user_content}],
            output_format=schema,
            **options,
        )
    except anthropic.APITimeoutError as exc:
        raise LLMTimeout from exc
    except (
        anthropic.APIConnectionError,
        anthropic.RateLimitError,
        anthropic.InternalServerError,
    ) as exc:
        raise LLMUnavailable from exc
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise LLMUnavailable(f"no parsed output (stop_reason={response.stop_reason})")
    return response.parsed_output
