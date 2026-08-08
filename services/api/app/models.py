from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(word.capitalize() for word in tail)


class WireModel(BaseModel):
    """Base for models the browser reads.

    Python keeps snake_case; the wire format is camelCase. FastAPI serializes
    response models by alias, so only the JSON changes.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Stage = Literal["extract", "transcribe", "align", "build", "package"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]

STAGES: tuple[Stage, ...] = ("extract", "transcribe", "align", "build", "package")

STAGE_LABELS: dict[Stage, str] = {
    "extract": "Extract",
    "transcribe": "Transcribe",
    "align": "Align",
    "build": "Build overlays",
    "package": "Package",
}


class Health(WireModel):
    ok: bool = True
    version: str


class JobCreate(WireModel):
    title: str = Field(min_length=1, max_length=200)


class Job(WireModel):
    job_id: str
    title: str
    status: JobStatus
    stage: Stage | None = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class JobEvent(WireModel):
    """One entry on a job's event stream."""

    type: Literal["snapshot", "progress", "done"]
    job: Job
