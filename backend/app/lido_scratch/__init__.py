"""Generate a Lido.js document from scratch — no template retrieval.

Where `app.lido_corpus` picks the nearest existing template and rewrites its slots,
this package has the LLM *design* the page: canvas, palette, type scale, element
placement and copy, all from the brief alone. The output is the same
`[{"layers": {...}, "meta": {...}}]` shape, so everything downstream (preview,
editor, the enrichment script) works on it unchanged.
"""

from .pipeline import ScratchResult, generate_scratch_design

__all__ = ["ScratchResult", "generate_scratch_design"]
