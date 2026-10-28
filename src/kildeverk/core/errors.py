"""The one error shape every tool returns, over MCP and REST alike.

An agent reading an error needs four things: what kind of failure it is, whether
trying again can help, how long to wait if so, and what to call instead. Stack
traces and validation dumps answer none of those, so they never leave the process.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    TOO_LARGE = "TOO_LARGE"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_CHANGED = "UPSTREAM_CHANGED"
    NOT_CONVERTIBLE = "NOT_CONVERTIBLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    INTERNAL = "INTERNAL"


# Whether the same call can succeed later without changing its arguments.
_RETRYABLE = {
    ErrorCode.RATE_LIMITED: True,
    ErrorCode.UPSTREAM_UNAVAILABLE: True,
    ErrorCode.UPSTREAM_TIMEOUT: True,
}

HTTP_STATUS = {
    ErrorCode.INVALID_ARGUMENT: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.AMBIGUOUS: 409,
    ErrorCode.TOO_LARGE: 413,
    ErrorCode.NOT_CONVERTIBLE: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL: 500,
    ErrorCode.NOT_CONFIGURED: 501,
    ErrorCode.UPSTREAM_UNAVAILABLE: 502,
    ErrorCode.UPSTREAM_CHANGED: 502,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
}


class NextCall(BaseModel):
    """A call that is likely to work where this one did not."""

    tool: str
    arguments: dict[str, Any]


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str = Field(description="Plain explanation of what went wrong and what to do.")
    retryable: bool = Field(description="True if repeating the same call later can succeed.")
    retry_after_s: float | None = Field(
        default=None, description="Seconds to wait before retrying, when rate limited."
    )
    next_call: NextCall | None = None
    source_id: str | None = None
    upstream_status: int | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class ToolError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool | None = None,
        retry_after_s: float | None = None,
        next_call: NextCall | None = None,
        source_id: str | None = None,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(
            code=code,
            message=message,
            retryable=_RETRYABLE.get(code, False) if retryable is None else retryable,
            retry_after_s=None if retry_after_s is None else round(retry_after_s, 1),
            next_call=next_call,
            source_id=source_id,
            upstream_status=upstream_status,
        )

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.body.code]

    def envelope(self) -> dict[str, Any]:
        return ErrorEnvelope(error=self.body).model_dump(mode="json", exclude_none=True)


def from_validation_error(exc: ValidationError, *, tool: str | None = None) -> ToolError:
    """One plain sentence per bad field, without echoing the input back."""

    problems = []
    for err in exc.errors(include_url=False, include_input=False):
        where = ".".join(str(part) for part in err["loc"]) or "arguments"
        problems.append(f"{where}: {err['msg']}")
    subject = f"Arguments for {tool} are invalid" if tool else "Arguments are invalid"
    return ToolError(ErrorCode.INVALID_ARGUMENT, f"{subject}. " + "; ".join(problems) + ".")
