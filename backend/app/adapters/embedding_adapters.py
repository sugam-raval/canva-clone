"""Local sentence-transformer embedder.

Chosen over a hosted embedding API for template retrieval (§1.2) because retrieval runs
on every generation request: a local model removes a network round-trip from the §6
latency budget (retrieval is budgeted at 0.1 s) and removes the per-request cost
entirely. The model is small enough to keep resident on CPU, which §6.8 ("warm pools")
asks for anyway.

The embedding dimension follows the model, so `templates.embedding` is declared with the
configured dimension and `ensure_vector_dimension()` reconciles the column if the model
changes.
"""

from __future__ import annotations

import asyncio
import threading

import structlog

from app.adapters.base import AdapterError
from app.config import get_settings

log = structlog.get_logger(__name__)

# Dimensions of the models we expect to see, so the DB column can be sized without
# loading the model first.
KNOWN_DIMS: dict[str, int] = {
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/all-MiniLM-L12-v2": 384,
    "sentence-transformers/all-mpnet-base-v2": 768,
    "sentence-transformers/multi-qa-mpnet-base-dot-v1": 768,
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
    "intfloat/e5-base-v2": 768,
}


def expected_dim(model_name: str, fallback: int = 384) -> int:
    return KNOWN_DIMS.get(model_name, fallback)


class SentenceTransformerEmbedder:
    """Wraps `sentence_transformers.SentenceTransformer`.

    Loading is lazy and guarded: the first call pays the model load, every later call is
    a straight forward pass. Encoding runs in a worker thread so it never blocks the
    event loop.
    """

    def __init__(self, model_name: str | None = None, dim: int | None = None):
        settings = get_settings()
        self.model_name = model_name or settings.sentence_transformer_model
        self.name = f"local:{self.model_name}"
        self.dim = dim or expected_dim(self.model_name, settings.embedding_dim)
        self._model = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise AdapterError(
                        "sentence-transformers is not installed; "
                        "pip install -e '.[embed]'", recoverable=False) from exc
                log.info("embedder.loading", model=self.model_name)
                model = SentenceTransformer(self.model_name, device="cpu")
                # Renamed in sentence-transformers 4.x; support both.
                getter = getattr(model, "get_embedding_dimension", None) or \
                    model.get_sentence_embedding_dimension
                actual = int(getter())
                if actual != self.dim:
                    log.warning("embedder.dim_mismatch", declared=self.dim, actual=actual)
                    self.dim = actual
                self._model = model
                log.info("embedder.loaded", model=self.model_name, dim=self.dim)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def run() -> list[list[float]]:
            model = self._load()
            # Normalised vectors, so pgvector's cosine distance is a plain dot product.
            vectors = model.encode(texts, normalize_embeddings=True,
                                   convert_to_numpy=True, show_progress_bar=False)
            return [v.tolist() for v in vectors]

        try:
            return await asyncio.to_thread(run)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"sentence-transformer encode failed: {exc}") from exc

    def warm(self) -> None:
        """Pre-load at startup so the first user request does not pay the model load."""
        try:
            self._load()
        except AdapterError as exc:
            log.warning("embedder.warm_failed", error=str(exc))
