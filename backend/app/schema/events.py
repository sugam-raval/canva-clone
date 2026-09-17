"""Job and progress contracts — IMPLEMENTATION_PLAN §0.9."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from .brief import DesignBrief
from .doc import Base

# Part Two job types (decompose.*) are deliberately absent: that pipeline is deferred.
JobType = Literal[
    # Part One
    "brief.parse", "template.retrieve", "compose.layout",
    "asset.background", "asset.subject", "asset.object", "asset.icon", "asset.upscale",
    "harmonize.palette", "harmonize.contrast", "harmonize.shadow", "harmonize.color-match",
    "layout.solve", "doc.assemble", "doc.thumbnail",
    # Editing
    "layer.regenerate", "layer.restyle", "layer.remove-bg",
    "layer.expand", "layer.erase", "copy.rewrite",
    "export.render",
]

# One queue per resource class so GPU/paid work cannot starve cheap work (§0.9).
QUEUE_FOR_JOB: dict[str, str] = {
    "brief.parse": "q.llm",
    "compose.layout": "q.llm",
    "copy.rewrite": "q.llm",
    "template.retrieve": "q.llm",
    "asset.background": "q.image",
    "asset.object": "q.image",
    "asset.icon": "q.image",
    "layer.regenerate": "q.image",
    "layer.restyle": "q.image",
    "asset.subject": "q.image-alpha",
    "layer.remove-bg": "q.matting",
    "layer.expand": "q.inpaint",
    "layer.erase": "q.inpaint",
    "asset.upscale": "q.image",
    "harmonize.palette": "q.render",
    "harmonize.contrast": "q.render",
    "harmonize.shadow": "q.render",
    "harmonize.color-match": "q.render",
    "layout.solve": "q.render",
    "doc.assemble": "q.render",
    "doc.thumbnail": "q.render",
    "export.render": "q.export",
}

ALL_QUEUES = sorted(set(QUEUE_FOR_JOB.values()))


class JobEnvelope(Base):
    job_id: str
    request_id: str = Field(description="groups all jobs for one user action")
    doc_id: str
    layer_id: str | None = None
    type: JobType
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", description="= gen_hash where applicable")
    attempt: int = 0
    deadline_at: str = ""


# --------------------------------------------------------------------------------------
# Progress events, fanned out over WebSocket from Redis pub/sub `progress:{requestId}`
# --------------------------------------------------------------------------------------


class RequestStarted(Base):
    t: Literal["request.started"] = "request.started"
    request_id: str
    plan: list[str] = Field(default_factory=list)


class BriefReady(Base):
    t: Literal["brief.ready"] = "brief.ready"
    brief: DesignBrief


class DocSkeleton(Base):
    """Placeholders only — the client renders this immediately. Must arrive < 3 s."""

    t: Literal["doc.skeleton"] = "doc.skeleton"
    doc: dict[str, Any]


class JobStarted(Base):
    t: Literal["job.started"] = "job.started"
    job_id: str
    type: str
    layer_id: str | None = None


class LayerPatch(Base):
    t: Literal["layer.patch"] = "layer.patch"
    layer_id: str
    patch: dict[str, Any]


class JobFailed(Base):
    t: Literal["job.failed"] = "job.failed"
    job_id: str
    type: str
    recoverable: bool = True
    reason: str = ""


class DocSolved(Base):
    t: Literal["doc.solved"] = "doc.solved"
    doc: dict[str, Any]
    violations: list[dict[str, Any]] = Field(default_factory=list)


class RequestDone(Base):
    t: Literal["request.done"] = "request.done"
    doc_id: str
    cost_cents: int = 0
    tier: str = "full"
    summary: str = ""


class RequestFailed(Base):
    t: Literal["request.failed"] = "request.failed"
    reason: str


class Clarify(Base):
    """§1.1 allows exactly one clarifying question, with tappable options."""

    t: Literal["request.clarify"] = "request.clarify"
    request_id: str
    question: str
    options: list[str] = Field(default_factory=list)


ProgressEvent = Annotated[
    RequestStarted | BriefReady | DocSkeleton | JobStarted | LayerPatch | JobFailed | DocSolved | RequestDone | RequestFailed | Clarify,
    Field(discriminator="t"),
]
