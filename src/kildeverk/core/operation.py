"""A tool, declared once and served over MCP, REST and the website catalogue."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, ToolError, from_validation_error

if TYPE_CHECKING:
    from kildeverk.context import Context

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Operation:
    name: str
    title: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[Context, Any], Awaitable[Result[Any]]]
    source_ids: tuple[str, ...]
    http_method: Literal["GET", "POST"]
    http_path: str
    examples: tuple[dict[str, Any], ...] = field(default=())

    @property
    def result_model(self) -> type[BaseModel]:
        return Result[self.output_model]  # type: ignore[name-defined]

    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def output_schema(self) -> dict[str, Any]:
        return self.result_model.model_json_schema()

    async def invoke(self, ctx: Context, arguments: dict[str, Any] | BaseModel) -> dict[str, Any]:
        """Validate, run and serialise. Raises ToolError and nothing else."""

        if isinstance(arguments, self.input_model):
            args = arguments
        else:
            try:
                args = self.input_model.model_validate(arguments or {})
            except ValidationError as exc:
                raise from_validation_error(exc, tool=self.name) from None
        try:
            result = await self.handler(ctx, args)
        except ToolError:
            raise
        except ValidationError:
            log.exception("upstream response for %s did not parse", self.name)
            raise ToolError(
                ErrorCode.UPSTREAM_CHANGED,
                "The upstream response did not have the expected shape; its API may have changed. "
                "This has been logged.",
                source_id=self.source_ids[0] if self.source_ids else None,
            ) from None
        except Exception:
            log.exception("unexpected failure in %s", self.name)
            raise ToolError(
                ErrorCode.INTERNAL,
                f"{self.name} failed unexpectedly. This has been logged; retrying is unlikely to help.",
            ) from None
        return result.model_dump(mode="json")
