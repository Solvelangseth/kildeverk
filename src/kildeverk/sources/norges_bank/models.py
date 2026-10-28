from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Currency = Annotated[
    str,
    Field(
        pattern=r"^[A-Z0-9]{3}$",
        description="ISO code such as 'EUR', or one of Norges Bank's indices ('I44', 'TWI').",
    ),
]

FREQUENCIES = {"daily": "B", "monthly": "M", "annual": "A"}


# --- currency_exchange_rates -------------------------------------------------------


class ExchangeRatesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currencies: list[Currency] = Field(
        default=["EUR", "USD", "GBP", "SEK", "DKK"], min_length=1, max_length=20
    )
    frequency: Literal["daily", "monthly", "annual"] = Field(
        default="daily", description="Daily rates (business days), or monthly or annual averages."
    )
    start: dt.date | None = Field(
        default=None, description="Leave start and end out for the latest."
    )
    end: dt.date | None = Field(default=None, description="Included.")
    max_rows: int = Field(default=1000, ge=1, le=10_000)

    @model_validator(mode="after")
    def _period(self) -> ExchangeRatesInput:
        if self.end is not None and self.start is None:
            raise ValueError("give start with end, or neither for the latest rates")
        if self.start and self.end and self.end < self.start:
            raise ValueError("end must not be before start")
        return self


class ExchangeRate(BaseModel):
    currency: str
    currency_name: str
    period: str = Field(description="'2026-10-27' daily, '2026-09' monthly, '2025' annual.")
    nok: float = Field(
        description="Kroner for `per` units of the currency, as Norges Bank quotes it."
    )
    per: int = Field(description="1, or 100 for currencies quoted per hundred (e.g. JPY, SEK).")
    nok_per_unit: float = Field(description="Kroner for one unit of the currency.")


class ExchangeRatesOutput(BaseModel):
    frequency: str
    row_count: int
    rows: list[ExchangeRate]


# --- rates_policy_rate -------------------------------------------------------------


class PolicyRateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    since: dt.date = Field(
        default_factory=lambda: dt.date.today() - dt.timedelta(days=5 * 365),
        description="List changes from this date. Defaults to five years ago.",
    )


class RateChange(BaseModel):
    effective: dt.date = Field(description="First business day at the new rate.")
    rate: float = Field(description="Per cent a year.")
    change_pp: float | None = Field(description="Change in percentage points.")


class PolicyRateOutput(BaseModel):
    rate: float = Field(description="The key policy rate now, per cent a year.")
    as_of: dt.date = Field(description="The latest business day in the data.")
    unchanged_since: dt.date | None = Field(
        description="When the current rate took effect, or null if before `since`."
    )
    changes: list[RateChange] = Field(description="Every change since `since`, oldest first.")
