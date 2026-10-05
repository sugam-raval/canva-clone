import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Settings tests depend on, pinned to the code's defaults whatever backend/.env says (an
# environment variable beats the .env file); set before the app is imported, since some
# are read at import.
os.environ["LIDO_MAX_PHOTOS"] = "4"
os.environ["LIDO_TEMPLATE_IMAGE_QUALITY"] = "high"


import pytest


@pytest.fixture(autouse=True)
def _no_template_database(monkeypatch):
    """Tests never read or write the real lido_templates table: the catalog is built
    from the files in memory (LIDO_TEMPLATE_STORE=files)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "lido_template_store", "files")
