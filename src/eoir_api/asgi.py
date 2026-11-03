from litestar import Litestar

from eoir_api.app import create_app
from eoir_api.settings import Settings, find_config


def app_from_env() -> Litestar:
    """Create the app from the config file named by ``$EOIR_API_CONFIG``."""
    return create_app(Settings.load(find_config()))
