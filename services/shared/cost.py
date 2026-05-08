from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def _as_decimal(value: str) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _env_decimal(name: str, fallback: str) -> Decimal:
    return _as_decimal(os.environ.get(name, fallback))


PRICING_USD_PER_MILLION: dict[str, dict[str, Decimal]] = {
    "gpt-4o-mini": {
        "input": _env_decimal("COST_GPT_4O_MINI_INPUT_PER_M", "0.15"),
        "output": _env_decimal("COST_GPT_4O_MINI_OUTPUT_PER_M", "0.60"),
    },
    "text-embedding-3-large": {
        "input": _env_decimal("COST_EMBED_3_LARGE_INPUT_PER_M", "0.13"),
    },
    "text-embedding-3-small": {
        "input": _env_decimal("COST_EMBED_3_SMALL_INPUT_PER_M", "0.02"),
    },
}


def _model_price(model: str, key: str) -> Decimal:
    config = PRICING_USD_PER_MILLION.get((model or "").strip(), {})
    value = config.get(key)
    if value is None:
        return Decimal("0")
    return value


def compute_chat_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    prompt = max(int(prompt_tokens or 0), 0)
    completion = max(int(completion_tokens or 0), 0)
    per_m_input = _model_price(model, "input")
    per_m_output = _model_price(model, "output")
    cost = (Decimal(prompt) * per_m_input / Decimal("1000000")) + (
        Decimal(completion) * per_m_output / Decimal("1000000")
    )
    return _money(cost)


def compute_embedding_cost(model: str, total_tokens: int) -> Decimal:
    tokens = max(int(total_tokens or 0), 0)
    per_m_input = _model_price(model, "input")
    cost = Decimal(tokens) * per_m_input / Decimal("1000000")
    return _money(cost)


def parse_usage_tokens(usage: Any) -> tuple[int, int, int]:
    if usage is None:
        return 0, 0, 0
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    return prompt_tokens, completion_tokens, total_tokens


def record_cost(
    service: str,
    kind: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost_usd: Decimal,
    file_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    try:
        from db import ApiCostEvent, get_db_context  # type: ignore
    except Exception:
        return

    with get_db_context() as db:
        row = ApiCostEvent(
            service=service,
            kind=kind,
            model=model,
            prompt_tokens=max(int(prompt_tokens or 0), 0),
            completion_tokens=max(int(completion_tokens or 0), 0),
            total_tokens=max(int(total_tokens or 0), 0),
            cost_usd=cost_usd,
            file_id=file_id,
            meta=meta or {},
        )
        db.add(row)

