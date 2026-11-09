from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from litestar.datastructures import MutableScopeHeaders
from litestar.enums import ScopeType
from litestar.middleware import ASGIMiddleware

if TYPE_CHECKING:
    from litestar.types import ASGIApp, Message, Receive, Scope, Send


class RequestIdMiddleware(ASGIMiddleware):
    """Tag a request's logs and response with a generated ``x-request-id``."""

    scopes = (ScopeType.HTTP,)

    async def handle(
        self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        request_id = uuid4().hex

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableScopeHeaders.from_message(message)["x-request-id"] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            await next_app(scope, receive, send_with_id)
