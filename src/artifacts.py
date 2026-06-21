from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    path: str = Field(
        ...,
        description="Path relative to the project directory."
    )
    artifact_type: str = Field(
        ...,
        description="Artifact type, such as markdown, text, log, json, csv, or unknown."
    )
    size_bytes: int
    modified_time: str
    content_preview: Optional[str] = None
    parser_status: str = "parsed"


class ArtifactIndex(BaseModel):
    project_dir: str
    artifacts: List[ArtifactRecord] = Field(default_factory=list)


class ParsedArtifact(BaseModel):
    path: str = Field(
        ...,
        description="Path relative to the project directory."
    )
    artifact_type: str
    content_for_llm: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class ParsedArtifactBundle(BaseModel):
    project_dir: str
    artifacts: List[ParsedArtifact] = Field(default_factory=list)
