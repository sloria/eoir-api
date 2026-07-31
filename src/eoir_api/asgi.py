from eoir_api.app import create_app
from eoir_api.settings import Settings

app = create_app(Settings.from_env())
