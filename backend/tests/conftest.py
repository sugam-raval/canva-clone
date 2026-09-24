import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


import pytest


@pytest.fixture(autouse=True)
def _no_template_database(monkeypatch):
    """Tests never read or write the real lido_templates table: the catalog is built
    from the files in memory (LIDO_TEMPLATE_STORE=files)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "lido_template_store", "files")
