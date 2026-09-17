"""Token and cost accounting.

Pricing is configuration, not code: providers change prices, and a template that
bakes them in is wrong the week after it ships.

The important property here is honesty about provenance. Some providers report
usage during streaming and some do not, so every figure is labelled as measured
or estimated and the UI says which. A cost table that silently mixes the two is
a cost table nobody should trust.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.providers.base import Usage, UsageSource

TOKENS_PER_UNIT = Decimal(1_000_000)
# Six places: at $0.15/1M, a 40-token reply costs $0.000006. Rounding to four
# would report every short message as free.
COST_PRECISION = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Pricing:
    input_per_1m: Decimal
    output_per_1m: Decimal
    currency: str

    @classmethod
    def from_settings(cls, settings) -> Pricing:
        return cls(
            input_per_1m=Decimal(str(settings.llm_price_input_per_1m)),
            output_per_1m=Decimal(str(settings.llm_price_output_per_1m)),
            currency=settings.llm_price_currency,
        )

    @property
    def is_free(self) -> bool:
        """Both rates zero means cost is not being tracked, not that it is $0."""
        return self.input_per_1m == 0 and self.output_per_1m == 0


@dataclass(frozen=True, slots=True)
class Accounting:
    prompt_tokens: int
    completion_tokens: int
    cost: Decimal
    currency: str
    source: UsageSource

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_event(self) -> dict[str, object]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": float(self.cost),
            "currency": self.currency,
            "source": str(self.source),
        }


def price(usage: Usage, pricing: Pricing) -> Accounting:
    cost = (
        Decimal(usage.prompt_tokens) * pricing.input_per_1m
        + Decimal(usage.completion_tokens) * pricing.output_per_1m
    ) / TOKENS_PER_UNIT
    return Accounting(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cost=cost.quantize(COST_PRECISION, rounding=ROUND_HALF_UP),
        currency=pricing.currency,
        source=usage.source,
    )


def summarise(messages, pricing: Pricing) -> dict[str, object]:
    """Roll message-level accounting up to a conversation total.

    Reads the stored per-message figures rather than re-pricing, so a total
    stays consistent with the rows it came from even after prices change in
    `.env`.
    """
    prompt = sum(m.prompt_tokens for m in messages)
    completion = sum(m.completion_tokens for m in messages)
    cost = sum((Decimal(str(m.cost)) for m in messages), Decimal(0))
    estimated = any(m.usage_source == UsageSource.ESTIMATED for m in messages)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cost": cost.quantize(COST_PRECISION, rounding=ROUND_HALF_UP),
        "currency": pricing.currency,
        "estimated": estimated,
    }
