"""Runtime configuration. Every model and service is selected by env var so adapters
stay swappable (IMPLEMENTATION_PLAN §0.3, Appendix B)."""

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
    redis_url: str = "redis://localhost:6380/0"

    # -- object storage (§0.8) --------------------------------------------------------
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
    embedding_model: str = "text-embedding-3-small"
    # Local embedder used for template retrieval (§1.2). Dimension follows the model;
    # `scripts/seed_templates.py` reconciles the `templates.embedding` column to match.
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    image_model: str = "gpt-image-2.5-sunburst"
    # The Lido.js (template) flow makes a single LLM call per design that writes every
    # layer's copy and both image prompts at once, so it gets more thinking than the
    # global default. Only applies when llm_reasoning_effort is set (a reasoning model).
    lido_template_reasoning_effort: str = "high"
    lido_template_image_quality: str = Field(default="high", description="low | medium | high")

    # -- adapter selection (§0.3) -----------------------------------------------------
    # "auto" means best available, degrading silently when a key or dependency is
    # missing; naming a provider explicitly means "I insist", and the registry warns
    # loudly if it cannot honour that. /v1/health always reports what resolved.
    adapter_text_to_image: str = Field(default="auto", description="auto | openai | stub")
    adapter_transparent_image: str = Field(
        default="auto", description="auto | openai | matte | stub")
    adapter_inpainter: str = Field(default="auto", description="auto | openai | opencv | stub")
    adapter_matting: str = Field(default="auto", description="auto | rembg | opencv | stub")
    adapter_glyph_detector: str = Field(default="auto", description="auto | opencv | stub")
    adapter_embedder: str = Field(
        default="sentence-transformers",
        description="sentence-transformers | openai | hash")
    adapter_llm: str = Field(default="auto", description="auto | openai | stub")

    # -- pipeline behaviour -----------------------------------------------------------
    default_image_steps: int = 28
    glyph_gate_max_coverage: float = 0.004      # §1.4.6
    glyph_gate_max_boxes: int = 2
    glyph_gate_retries: int = 2
    job_retry_attempts: int = 3
    job_backoff_seconds: tuple[int, ...] = (2, 8, 30)
    skeleton_deadline_seconds: float = 3.0      # §0.9 hard requirement
    request_deadline_seconds: float = 120.0

    # -- cost controls (§6.7) ---------------------------------------------------------
    max_cost_cents_per_request: int = 200
    max_cost_cents_per_user_per_day: int = 2000
    rate_limit_generations_per_hour: int = 60

    # -- safety (§7) ------------------------------------------------------------------
    enable_content_filter: bool = True
    asset_retention_days: int = 30

    # -- server -----------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    dev_user_email: str = "dev@localhost"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
