# ADR 0002 — Local sentence-transformer embeddings for template retrieval

Status: accepted — 2026-09-11
Refines IMPLEMENTATION_PLAN.md §1.2 and Appendix B.

## Context

§1.2 retrieves layout skeletons by embedding the brief and comparing it against
`templates.description` with pgvector. Appendix B lists `text-embedding-3-small`
(hosted) as the embedder.

Retrieval runs on **every** generation request, and §6 budgets it at 0.1 s inside a
3 s deadline for `doc.skeleton`. A hosted embedding call puts a network round-trip
and a per-request cost on that path.

The corpus is also small — tens of skeletons, each with a one-paragraph description
written as a design brief. This is a domain where a compact general-purpose sentence
encoder is entirely adequate; the discriminating signal is mostly which *kind* and
*aspect* the brief needs, and those are hard filters applied before the vector search.

## Decision

Use `sentence-transformers/all-MiniLM-L6-v2` on CPU as the default `Embedder`,
loaded once per process and kept resident.

- 384 dimensions, ~90 MB of weights, ~5 ms per query once warm.
- `templates.embedding` is declared `vector(384)`; `scripts/seed_templates.py`
  reconciles the column automatically if the model (and therefore the dimension)
  changes, because pgvector rejects mismatched inserts with an opaque error.
- Vectors are L2-normalised at encode time, so pgvector's cosine distance is a plain
  dot product.
- `ADAPTER_EMBEDDER=openai` still selects the hosted embedder; the interface is
  unchanged.

`torch` must be installed from the CPU wheel index. The default wheel pulls roughly
3 GB of CUDA libraries that a CPU-only host cannot use:

```
uv pip install --extra-index-url https://download.pytorch.org/whl/cpu -e "backend[embed]"
```

## Consequences

**Good.** No network hop and no per-request cost on the hottest path. Retrieval
works fully offline, which is what lets the whole pipeline run without an API key.

**Cost.** The model load is ~18 s. That is far larger than the 3 s skeleton budget,
so it must not happen on a user's first request: the API warms the embedder during
FastAPI's lifespan startup, and the eval harness warms it before timing anything.
This is §6.8's "warm pools" requirement, and it is not optional — an unwarmed process
fails the §5.3 `p95_skeleton_seconds` gate on the first prompt alone.

**Quality.** MiniLM is weaker than `text-embedding-3-small` at fine-grained semantic
distinctions. It is sufficient here because hard filters (kind, aspect, text-only vs
subject) do most of the work and similarity only orders the survivors. If retrieval
quality becomes the limiting factor on output quality, switch `ADAPTER_EMBEDDER` and
re-seed — but suspect the **corpus size** first: 17 skeletons is the real constraint,
not the encoder.

## Alternatives rejected

- **`fastembed` (ONNX, no torch).** Smaller install and no torch dependency, but the
  project owner asked for sentence-transformers specifically.
- **Hosted `text-embedding-3-small`.** Better embeddings, but puts a paid network
  call inside the skeleton deadline and makes offline operation impossible.
- **Hash-based bag-of-words.** Retained as the last-resort fallback
  (`ADAPTER_EMBEDDER=hash`); it has no semantics and is not representative of
  retrieval quality.
