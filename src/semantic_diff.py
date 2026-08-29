import json
import os

from pydantic import BaseModel, Field
from pathlib import Path

from alignment_models import (
    AlignmentGroup,
    FieldAlignment,
    ProjectStateAlignment,
    UncertainAlignment,
)


PROJECT_STATE_LIST_FIELDS = (
    "confirmed_findings",
    "tentative_hypotheses",
    "important_decisions",
    "failed_attempts",
    "open_questions",
    "next_actions",
)

class _IndexGroup(BaseModel):
    old_indexes: list[int] = Field(default_factory=list)
    new_indexes: list[int] = Field(default_factory=list)
    reason: str = ""


class _IndexAlignment(BaseModel):
    field: str
    unchanged: list[_IndexGroup] = Field(default_factory=list)
    added: list[int] = Field(default_factory=list)
    removed: list[int] = Field(default_factory=list)
    revised: list[_IndexGroup] = Field(default_factory=list)
    uncertain: list[_IndexGroup] = Field(default_factory=list)


SEMANTIC_ALIGNMENT_PROMPT = """You align two versions of one ProjectState list field.

Compare only the supplied old and new items. Do not infer project facts or use
outside knowledge.

Use two passes:

Pass A — direct and group alignment:
- Match items that express the same underlying project fact.
- Build one-to-one, one-to-many, many-to-one, or many-to-many groups.
- Use unchanged for equivalent meaning, including paraphrases, abbreviation
  expansions, summaries, restatements, implications, and detail/summary
  differences that preserve the overall meaning.

Pass B — global coverage check:
- Before labeling anything added or removed, compare it against all alignment
  groups, not just one item.
- If an item is a summary, restatement, implication, more compact version, or
  more explicit version of information already covered on the other side, add
  it to that unchanged group.
- Added and removed are last-resort classifications.

Classification rules:
- revised: the same underlying claim has a substantive change in number,
  conclusion, status, scope, or actionability.
- Do not mark clearer wording, abbreviation expansion, the same uncertainty
  restated, or summary/detail rephrasing as revised.
- added: genuinely new information with no old equivalent.
- removed: genuinely absent, resolved, completed, or no longer supported
  information with no new equivalent.
- uncertain: plausible relationship that cannot be classified confidently.
- Be conservative. Prefer uncertain over inventing an added/removed pair.
- Refer to items only by their integer indexes.
- Every supplied index must occur exactly once across the output categories.
- Never place the same semantic item in both added and removed.

Examples:
- Old broad claim "Performance depends on workload" and new specific claims
  "improves on small workloads" plus "regresses on large workloads" are one
  unchanged group when the specific claims cover the same overall fact.
- "Cause A or B may explain the regression" and "Both A and B are possible;
  the primary cause is unknown" are unchanged uncertainty restatements.
- "Preliminary latency was 92ms" changing to "Corrected latency is 97ms" is
  revised, not added plus removed.

Return valid JSON only:
{{
  "field": "{field}",
  "unchanged": [
    {{"old_indexes": [0], "new_indexes": [0, 1], "reason": "..."}}
  ],
  "added": [2],
  "removed": [3],
  "revised": [
    {{"old_indexes": [1], "new_indexes": [3], "reason": "..."}}
  ],
  "uncertain": [
    {{"old_indexes": [2], "new_indexes": [4], "reason": "..."}}
  ]
}}

Compact project metadata:
{metadata}

Old items:
{old_items}

New items:
{new_items}
"""

RETRY_INSTRUCTION = """

Your previous output was invalid.

Previous output:
{invalid_output}

Validation error:
{validation_error}

Return corrected JSON only. Every old and new index must appear exactly once
across unchanged, added, removed, revised, and uncertain. Do not omit or repeat
an index.
"""


def _extract_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text.removeprefix("```json").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").strip()
    if text.endswith("```"):
        text = text.removesuffix("```").strip()
    return text


def _validate_index_coverage(
    alignment: _IndexAlignment,
    old_items: list[str],
    new_items: list[str],
) -> None:
    aligned_old = alignment.removed.copy()
    aligned_new = alignment.added.copy()
    for group in alignment.unchanged + alignment.revised + alignment.uncertain:
        aligned_old.extend(group.old_indexes)
        aligned_new.extend(group.new_indexes)

    if sorted(aligned_old) != list(range(len(old_items))):
        raise ValueError(f"Semantic alignment did not cover old {alignment.field} items.")
    if sorted(aligned_new) != list(range(len(new_items))):
        raise ValueError(f"Semantic alignment did not cover new {alignment.field} items.")


def repair_index_alignment_coverage(
    alignment: _IndexAlignment,
    old_items: list[str],
    new_items: list[str],
) -> tuple[_IndexAlignment, list[str]]:
    """Repair index bookkeeping without inferring semantic relationships."""
    notes: list[str] = []
    used_old: set[int] = set()
    used_new: set[int] = set()
    repaired_unchanged: list[_IndexGroup] = []
    repaired_revised: list[_IndexGroup] = []
    repaired_uncertain: list[_IndexGroup] = []

    def keep_indexes(
        indexes: list[int],
        used: set[int],
        upper_bound: int,
        label: str,
    ) -> list[int]:
        kept = []
        for index in indexes:
            if index < 0 or index >= upper_bound:
                notes.append(f"Dropped out-of-range {label} index {index}.")
                continue
            if index in used:
                notes.append(f"Dropped duplicate {label} index {index}.")
                continue
            used.add(index)
            kept.append(index)
        return kept

    def repair_two_sided_group(
        group: _IndexGroup,
        category: str,
        destination: list[_IndexGroup],
    ) -> None:
        old_indexes = keep_indexes(
            group.old_indexes, used_old, len(old_items), "old"
        )
        new_indexes = keep_indexes(
            group.new_indexes, used_new, len(new_items), "new"
        )
        if old_indexes and new_indexes:
            destination.append(
                _IndexGroup(
                    old_indexes=old_indexes,
                    new_indexes=new_indexes,
                    reason=group.reason,
                )
            )
            return
        if old_indexes or new_indexes:
            notes.append(
                f"Moved one-sided {category} group to uncertain after repair."
            )
            repaired_uncertain.append(
                _IndexGroup(
                    old_indexes=old_indexes,
                    new_indexes=new_indexes,
                    reason=(
                        "Alignment group became one-sided during structural "
                        "repair; semantic relationship uncertain."
                    ),
                )
            )
        else:
            notes.append(f"Dropped empty {category} group after repair.")

    for group in alignment.unchanged:
        repair_two_sided_group(group, "unchanged", repaired_unchanged)
    for group in alignment.revised:
        repair_two_sided_group(group, "revised", repaired_revised)
    for group in alignment.uncertain:
        old_indexes = keep_indexes(
            group.old_indexes, used_old, len(old_items), "old"
        )
        new_indexes = keep_indexes(
            group.new_indexes, used_new, len(new_items), "new"
        )
        if old_indexes or new_indexes:
            repaired_uncertain.append(
                _IndexGroup(
                    old_indexes=old_indexes,
                    new_indexes=new_indexes,
                    reason=group.reason,
                )
            )
        else:
            notes.append("Dropped empty uncertain group after repair.")

    repaired_removed = keep_indexes(
        alignment.removed, used_old, len(old_items), "old"
    )
    repaired_added = keep_indexes(
        alignment.added, used_new, len(new_items), "new"
    )

    missing_old = [index for index in range(len(old_items)) if index not in used_old]
    missing_new = [index for index in range(len(new_items)) if index not in used_new]
    uncovered_reason = (
        "Uncovered indexes after alignment repair; semantic relationship uncertain."
    )
    if len(missing_old) == 1 and len(missing_new) == 1:
        repaired_uncertain.append(
            _IndexGroup(
                old_indexes=missing_old,
                new_indexes=missing_new,
                reason=uncovered_reason,
            )
        )
        notes.append(
            f"Placed missing old index {missing_old[0]} and new index "
            f"{missing_new[0]} into one uncertain group."
        )
    else:
        for index in missing_old:
            repaired_uncertain.append(
                _IndexGroup(
                    old_indexes=[index],
                    reason=uncovered_reason,
                )
            )
            notes.append(f"Placed missing old index {index} into uncertain.")
        for index in missing_new:
            repaired_uncertain.append(
                _IndexGroup(
                    new_indexes=[index],
                    reason=uncovered_reason,
                )
            )
            notes.append(f"Placed missing new index {index} into uncertain.")

    repaired = _IndexAlignment(
        field=alignment.field,
        unchanged=repaired_unchanged,
        revised=repaired_revised,
        uncertain=repaired_uncertain,
        removed=repaired_removed,
        added=repaired_added,
    )
    _validate_index_coverage(repaired, old_items, new_items)
    return repaired, notes


def _materialize_group(
    group: _IndexGroup,
    old_items: list[str],
    new_items: list[str],
) -> AlignmentGroup:
    return AlignmentGroup(
        old_items=[old_items[index] for index in group.old_indexes],
        new_items=[new_items[index] for index in group.new_indexes],
        reason=group.reason,
    )


def align_field_with_llm(
    *,
    field: str,
    old_items: list[str],
    new_items: list[str],
    model: str,
    project_name: str | None = None,
    current_stage: str | None = None,
) -> tuple[FieldAlignment, dict[str, object] | None]:
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Semantic diff requires openai and python-dotenv."
        ) from exc

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for --semantic-diff.")

    metadata = {
        "project_name": project_name,
        "current_stage": current_stage,
    }
    prompt = SEMANTIC_ALIGNMENT_PROMPT.format(
        field=field,
        metadata=json.dumps(metadata, ensure_ascii=False),
        old_items=json.dumps(old_items, ensure_ascii=False),
        new_items=json.dumps(new_items, ensure_ascii=False),
    )
    client = OpenAI()
    invalid_output = ""
    validation_error = ""
    original_coverage_error = ""
    for attempt in range(2):
        current_prompt = prompt
        if attempt == 1:
            current_prompt += RETRY_INSTRUCTION.format(
                invalid_output=invalid_output or "No usable output.",
                validation_error=validation_error,
            )
        response = client.responses.create(model=model, input=current_prompt)
        invalid_output = response.output_text
        try:
            data = json.loads(_extract_json_text(invalid_output))
            index_alignment = _IndexAlignment.model_validate(data)
            if index_alignment.field != field:
                raise ValueError(
                    f"Semantic aligner returned field {index_alignment.field!r}, "
                    f"expected {field!r}."
                )
        except Exception as exc:
            validation_error = str(exc)
            continue

        try:
            _validate_index_coverage(index_alignment, old_items, new_items)
            repair_diagnostic = None
        except ValueError as exc:
            validation_error = str(exc)
            if attempt == 0:
                original_coverage_error = validation_error
                continue
            repaired_alignment, repair_notes = repair_index_alignment_coverage(
                index_alignment,
                old_items,
                new_items,
            )
            index_alignment = repaired_alignment
            repair_diagnostic = {
                "repair_succeeded": True,
                "original_coverage_error": original_coverage_error or None,
                "retry_coverage_error": validation_error,
                "repair_notes": repair_notes,
            }

        return (
            FieldAlignment(
                field=field,
                unchanged=[
                    _materialize_group(group, old_items, new_items)
                    for group in index_alignment.unchanged
                ],
                added=[new_items[index] for index in index_alignment.added],
                removed=[old_items[index] for index in index_alignment.removed],
                revised=[
                    _materialize_group(group, old_items, new_items)
                    for group in index_alignment.revised
                ],
                uncertain=[
                    UncertainAlignment.model_validate(
                        _materialize_group(group, old_items, new_items).model_dump()
                    )
                    for group in index_alignment.uncertain
                ],
            ),
            repair_diagnostic,
        )

    raise ValueError(
        f"Semantic alignment failed for field {field!r} after one retry: "
        f"{validation_error}"
    )


def align_project_state_fields(
    *,
    old_state: object,
    new_state: object,
    model: str,
) -> tuple[
    dict[str, FieldAlignment],
    dict[str, str],
    dict[str, dict[str, object]],
]:
    from diff_states import deterministic_alignment

    alignments: dict[str, FieldAlignment] = {}
    errors: dict[str, str] = {}
    repairs: dict[str, dict[str, object]] = {}
    for field in PROJECT_STATE_LIST_FIELDS:
        old_items = list(getattr(old_state, field))
        new_items = list(getattr(new_state, field))
        try:
            alignment, repair_diagnostic = align_field_with_llm(
                field=field,
                old_items=old_items,
                new_items=new_items,
                model=model,
                project_name=getattr(new_state, "project_name", None),
                current_stage=getattr(new_state, "current_stage", None),
            )
            alignments[field] = alignment
            if repair_diagnostic is not None:
                repairs[field] = repair_diagnostic
        except Exception as exc:
            errors[field] = str(exc)
            alignments[field] = deterministic_alignment(
                field,
                old_items,
                new_items,
            )
    return alignments, errors, repairs


def run_semantic_diff_workflow(
    *,
    old_state: object,
    new_state: object,
    model: str,
    output_dir: Path,
    project_name: str | None,
    run_label: str,
) -> dict[str, FieldAlignment] | None:
    try:
        field_alignments, alignment_errors, alignment_repairs = (
            align_project_state_fields(
                old_state=old_state,
                new_state=new_state,
                model=model,
            )
        )

        semantic_alignments_path = output_dir / "semantic_alignments.json"
        semantic_alignments_path.write_text(
            json.dumps(
                {
                    "semantic_diff_model": model,
                    "project_name": project_name,
                    "run_dir": run_label,
                    "fallback_fields": sorted(alignment_errors),
                    "repaired_fields": sorted(alignment_repairs),
                    "repair_diagnostics": alignment_repairs,
                    "fields": {
                        field: alignment.model_dump()
                        for field, alignment in field_alignments.items()
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(f"Semantic diff model: {model}")
        print(f"Semantic alignments: {semantic_alignments_path}")

        if alignment_errors or alignment_repairs:
            semantic_error_path = output_dir / "semantic_alignments_error.json"
            semantic_error_path.write_text(
                json.dumps(
                    {
                        "semantic_diff_model": model,
                        "project_name": project_name,
                        "run_dir": run_label,
                        "fallback": (
                            "deterministic_per_field"
                            if alignment_errors
                            else "none"
                        ),
                        "field_errors": alignment_errors,
                        "field_repairs": alignment_repairs,
                        "note": (
                            "Coverage repairs preserve valid classifications "
                            "and move uncovered indexes to uncertain. Failed "
                            "fields use deterministic fallback."
                        ),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            if alignment_repairs:
                print(
                    "Semantic alignment repaired fields: "
                    f"{', '.join(sorted(alignment_repairs))}"
                )

            if alignment_errors:
                print(
                    "Semantic alignment field fallbacks: "
                    f"{', '.join(sorted(alignment_errors))}"
                )

            print(f"Semantic alignment errors: {semantic_error_path}")

        return field_alignments

    except Exception as exc:
        semantic_error_path = output_dir / "semantic_alignments_error.json"
        semantic_error_path.write_text(
            json.dumps(
                {
                    "error": str(exc),
                    "semantic_diff_model": model,
                    "project_name": project_name,
                    "run_dir": run_label,
                    "fallback": "deterministic",
                    "note": (
                        "Semantic alignment failed; deterministic fallback "
                        "was used."
                    ),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            "Semantic diff unavailable; using deterministic fallback: "
            f"{exc}"
        )
        print(f"Semantic alignment error: {semantic_error_path}")

        return None
