"""Runtime configuration for the Lido.js (template) flow. Every model and service is
selected by env var, so adapters stay swappable."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", ROOT.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    log_level: str = "INFO"

    # -- infrastructure ---------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://design:design@localhost:5442/design"

    # -- object storage (generated images) --------------------------------------------------------
    storage_backend: str = Field(default="s3", description="'s3' or 'local'")
    s3_endpoint_url: str | None = "http://localhost:9010"
    s3_region: str = "us-east-1"
    s3_bucket: str = "design-assets"
    s3_access_key: str = "designminio"
    s3_secret_key: str = "designminio"
    s3_public_base_url: str | None = None
    signed_url_ttl_seconds: int = 3600
    local_storage_dir: Path = ROOT / "assets_local" / "store"

    # -- OpenAI (the only provider configured; everything sits behind an adapter) ------
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_model: str = "gpt-6-astra"
    # Reasoning effort for `llm_model`, passed to the Responses API's `reasoning.effort`
    # (none | minimal | low | medium | high | xhigh | max). Empty/None keeps `llm_model`
    # on the plain chat-completions path — set both this and llm_model together to swap
    # between a reasoning model (e.g. gpt-6-astra) and a non-reasoning one (gpt-4o*).
    llm_reasoning_effort: str | None = "low"
    llm_model_fast: str = "gpt-4o-mini"
    # Vision model for `scripts/enrich_lido_templates.py --draft-slots` (reading a
    # template's background/photo). Must be a chat-completions vision model; falls back
    # to llm_model_fast if the call fails.
    lido_enrich_vision_model: str = "gpt-4o"
    # Local embedding model for template matching (lido_templates.embedding). The column
    # is vector(384): changing to a model with another dimension needs the column altered.
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    # Where the template catalog lives: "db" (lido_templates in Postgres, synced from
    # lidojs_templates/*.json) or "files" (in-memory only, no database — tests use it).
    lido_template_store: str = Field(default="db", description="db | files")
    # How often a request re-checks the files for changes (a changed template is
    # re-embedded on the next request after this many seconds).
    lido_template_sync_seconds: float = 10.0
    image_model: str = "gpt-image-2.5-sunburst"
    # The Lido.js (template) flow's main fill call uses the global llm_reasoning_effort,
    # same as everywhere else; its repair call always uses llm_model_fast instead.
    lido_template_image_quality: str = Field(default="high", description="low | medium | high")

    # -- adapter selection ------------------------------------------------------------
    # "auto" means best available, degrading to the stub when no key is set.
    # /v1/health always reports what resolved.
    adapter_text_to_image: str = Field(default="auto", description="auto | openai | stub")
    adapter_transparent_image: str = Field(default="auto", description="auto | openai | stub")
    adapter_llm: str = Field(default="auto", description="auto | openai | stub")

    # -- server -----------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
