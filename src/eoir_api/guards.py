import hmac

from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler

from eoir_api.settings import Settings


def require_api_key(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    settings: Settings = connection.app.state.settings
    if not hmac.compare_digest(
        connection.headers.get("x-key", ""), settings.api_secret
    ):
        raise NotAuthorizedException("Invalid or missing x-key header")
