from typing import List, Optional
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str = Field(
        ...,
        description="The source file or artifact that supports the claim."
    )
    quote_or_summary: str = Field(
        ...,
        description="A short quote or summary from the source."
    )


class ProjectState(BaseModel):
    project_name: str
    one_sentence_summary: str
    goal: str
    current_stage: str

    confirmed_findings: List[str] = Field(
        default_factory=list,
        description="Facts directly supported by the provided notes."
    )
    tentative_hypotheses: List[str] = Field(
        default_factory=list,
        description="Plausible explanations or interpretations that are not fully proven."
    )
    important_decisions: List[str] = Field(
        default_factory=list,
        description="Important project decisions or direction choices."
    )
    failed_attempts: List[str] = Field(
        default_factory=list,
        description="Attempts that failed, were blocked, or did not work."
    )
    open_questions: List[str] = Field(
        default_factory=list,
        description="Unresolved questions that still need investigation."
    )
    next_actions: List[str] = Field(
        default_factory=list,
        description="Concrete next steps for the project."
    )
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="Evidence supporting important claims in the state."
    )

    last_updated: Optional[str] = Field(
        default=None,
        description="Optional date or timestamp for the state."
    )
