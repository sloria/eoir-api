import os

import msgspec
from litestar import Litestar

from eoir_api.app import create_app
from eoir_api.settings import DEBUG_ENV_VAR, Settings, find_config


def app_from_env() -> Litestar:
    """Create the app from the config file named by ``$EOIR_API_CONFIG``,
    in debug mode when ``$EOIR_API_DEBUG`` is set.
    """
    settings = Settings.load(find_config())
    if os.environ.get(DEBUG_ENV_VAR):
        settings = msgspec.structs.replace(settings, debug=True)
    return create_app(settings)
