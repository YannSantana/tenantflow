import logging
from .api import create_app
from .config import Settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
app = create_app(Settings())
