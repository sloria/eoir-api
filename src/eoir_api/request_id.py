from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from litestar.datastructures import Headers, MutableScopeHeaders
from litestar.enums import ScopeType
from litestar.middleware import ASGIMiddleware

if TYPE_CHECKING:
    from litestar.types import ASGIApp, Message, Receive, Scope, Send


HEADER = "x-request-id"


class RequestIdMiddleware(ASGIMiddleware):
    """Tag a request's logs and response with an ``x-request-id``."""

    scopes = (ScopeType.HTTP,)

    def __init__(self, *, trust_header: bool = False) -> None:
        # Allow requester to provide their own request ID
        self.trust_header = trust_header

    async def handle(
        self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        incoming = Headers.from_scope(scope).get(HEADER) if self.trust_header else None
        request_id = incoming or uuid4().hex

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableScopeHeaders.from_message(message)[HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            await next_app(scope, receive, send_with_id)
