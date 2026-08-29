from pydantic import BaseModel, Field, model_validator


class AlignmentGroup(BaseModel):
    old_items: list[str] = Field(default_factory=list)
    new_items: list[str] = Field(default_factory=list)
    reason: str = ""


class UncertainAlignment(AlignmentGroup):
    pass


class FieldAlignment(BaseModel):
    field: str
    unchanged: list[AlignmentGroup] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    revised: list[AlignmentGroup] = Field(default_factory=list)
    uncertain: list[UncertainAlignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_item_coverage(self) -> "FieldAlignment":
        for group in self.unchanged:
            if not group.old_items or not group.new_items:
                raise ValueError("Unchanged groups require old_items and new_items.")
        for group in self.revised:
            if not group.old_items or not group.new_items:
                raise ValueError("Revised groups require old_items and new_items.")
        return self


class ProjectStateAlignment(BaseModel):
    fields: list[FieldAlignment]
