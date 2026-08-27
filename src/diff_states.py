import re
import string
from difflib import SequenceMatcher
from typing import Literal, TypedDict

from artifacts import ParsedArtifactBundle
from schemas import ProjectState
from semantic_diff import AlignmentGroup, FieldAlignment


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this",
    "to", "was", "were", "with",
}


class ClaimComparison(TypedDict):
    relation: Literal["same", "revised", "different"]
    confidence: float
    reason: str


def _render_items(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def _artifact_hashes(bundle: ParsedArtifactBundle) -> dict[str, str]:
    return {artifact.path: artifact.content_hash for artifact in bundle.artifacts}


def _normalize_text(text: str) -> str:
    normalized = text.lower().replace("-", " ")
    normalized = re.sub(
        r"(\d+(?:\.\d+)?)\s*(milliseconds?|msecs?)\b",
        r"\1 ms",
        normalized,
    )
    normalized = re.sub(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?)\b", r"\1 s", normalized)
    normalized = normalized.translate(
        str.maketrans("", "", string.punctuation.replace(".", ""))
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _stem_token(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > 6 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _tokens(text: str) -> set[str]:
    raw_tokens = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", _normalize_text(text))
    return {
        _stem_token(token)
        for token in raw_tokens
        if token not in STOPWORDS and not token.replace(".", "", 1).isdigit()
    }


def _numbers(text: str) -> list[float]:
    values = []
    text = re.sub(r"\bp\d+\b", "", text.lower())
    for match in re.findall(r"(?<![a-zA-Z])[-+]?\d[\d,]*(?:\.\d+)?", text):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return values


def _numbers_equal(old_numbers: list[float], new_numbers: list[float]) -> bool:
    return len(old_numbers) == len(new_numbers) and all(
        abs(old - new) <= 1e-9
        for old, new in zip(sorted(old_numbers), sorted(new_numbers))
    )


def _token_overlap(old_tokens: set[str], new_tokens: set[str]) -> float:
    if not old_tokens and not new_tokens:
        return 1.0
    if not old_tokens or not new_tokens:
        return 0.0
    return len(old_tokens & new_tokens) / len(old_tokens | new_tokens)


def compare_claims(old_item: str, new_item: str) -> ClaimComparison:
    old_norm = _normalize_text(old_item)
    new_norm = _normalize_text(new_item)
    old_numbers = _numbers(old_item)
    new_numbers = _numbers(new_item)
    numbers_match = _numbers_equal(old_numbers, new_numbers)
    overlap = _token_overlap(_tokens(old_item), _tokens(new_item))
    sequence_ratio = SequenceMatcher(None, old_norm, new_norm).ratio()

    if old_norm == new_norm:
        return {"relation": "same", "confidence": 1.0, "reason": "normalized text matches"}

    if numbers_match and sequence_ratio >= 0.88 and overlap >= 0.72:
        return {
            "relation": "same",
            "confidence": min(sequence_ratio, overlap),
            "reason": "very high lexical similarity with identical numbers",
        }

    if (
        old_numbers
        and new_numbers
        and not numbers_match
        and sequence_ratio >= 0.78
        and overlap >= 0.65
    ):
        return {
            "relation": "revised",
            "confidence": min(sequence_ratio, overlap),
            "reason": "high lexical similarity with changed numeric values",
        }

    return {
        "relation": "different",
        "confidence": max(sequence_ratio, overlap),
        "reason": "deterministic comparison is not confident",
    }


def deterministic_alignment(
    field: str,
    old_items: list[str],
    new_items: list[str],
) -> FieldAlignment:
    unmatched_old = set(range(len(old_items)))
    unmatched_new = set(range(len(new_items)))
    unchanged: list[AlignmentGroup] = []
    revised: list[AlignmentGroup] = []
    candidates = []

    for old_index, old_item in enumerate(old_items):
        for new_index, new_item in enumerate(new_items):
            comparison = compare_claims(old_item, new_item)
            if comparison["relation"] != "different":
                candidates.append((comparison["confidence"], old_index, new_index, comparison))

    for _, old_index, new_index, comparison in sorted(candidates, reverse=True):
        if old_index not in unmatched_old or new_index not in unmatched_new:
            continue
        unmatched_old.remove(old_index)
        unmatched_new.remove(new_index)
        group = AlignmentGroup(
            old_items=[old_items[old_index]],
            new_items=[new_items[new_index]],
            reason=comparison["reason"],
        )
        if comparison["relation"] == "same":
            unchanged.append(group)
        else:
            revised.append(group)

    return FieldAlignment(
        field=field,
        unchanged=unchanged,
        revised=revised,
        added=[new_items[index] for index in sorted(unmatched_new)],
        removed=[old_items[index] for index in sorted(unmatched_old)],
    )


def diff_semantic_items(old_items: list[str], new_items: list[str]) -> dict[str, list[str]]:
    """Compatibility wrapper for deterministic callers."""
    alignment = deterministic_alignment("items", old_items, new_items)
    return {
        "added": alignment.added,
        "removed": alignment.removed,
        "revised": _render_revised(alignment.revised),
    }


def _render_revised(groups: list[AlignmentGroup]) -> list[str]:
    rendered = []
    for group in groups:
        old_text = " | ".join(group.old_items)
        new_text = " | ".join(group.new_items)
        reason = f" ({group.reason})" if group.reason else ""
        rendered.append(f"Revised: {old_text} → {new_text}{reason}")
    return rendered


def render_progress_since_last(
    old_state: ProjectState | None,
    new_state: ProjectState,
    old_parsed_artifacts: ParsedArtifactBundle | None = None,
    new_parsed_artifacts: ParsedArtifactBundle | None = None,
    field_alignments: dict[str, FieldAlignment] | None = None,
) -> str:
    lines = ["# Progress Since Last Checkpoint", ""]

    if old_state is None:
        lines.append("No previous checkpoint found.")
        return "\n".join(lines) + "\n"

    if old_parsed_artifacts is not None and new_parsed_artifacts is not None:
        old_hashes = _artifact_hashes(old_parsed_artifacts)
        new_hashes = _artifact_hashes(new_parsed_artifacts)
        added_artifacts = sorted(new_hashes.keys() - old_hashes.keys())
        removed_artifacts = sorted(old_hashes.keys() - new_hashes.keys())
        modified_artifacts = sorted(
            path for path in old_hashes.keys() & new_hashes.keys()
            if old_hashes[path] != new_hashes[path]
        )
        lines.extend(["## Source Artifact Changes", ""])
        if not added_artifacts and not removed_artifacts and not modified_artifacts:
            lines.extend([
                "No source artifact changes detected since the previous checkpoint.",
                "ProjectState diff skipped to avoid reporting LLM wording variation as progress.",
            ])
            return "\n".join(lines) + "\n"
        lines.extend([
            "### Added Artifacts", "", _render_items(added_artifacts), "",
            "### Removed Artifacts", "", _render_items(removed_artifacts), "",
            "### Changed Source Artifacts", "", _render_items(modified_artifacts), "",
        ])

    def alignment_for(field: str) -> FieldAlignment:
        if field_alignments and field in field_alignments:
            return field_alignments[field]
        return deterministic_alignment(
            field,
            list(getattr(old_state, field)),
            list(getattr(new_state, field)),
        )

    finding_diff = alignment_for("confirmed_findings")
    hypothesis_diff = alignment_for("tentative_hypotheses")
    semantic_change_count = (
        len(finding_diff.added) + len(finding_diff.removed) + len(finding_diff.revised)
        + len(hypothesis_diff.added) + len(hypothesis_diff.revised)
    )
    lines.extend([
        "## Current Snapshot", "", f"Current stage: {new_state.current_stage}", "",
        "## New Confirmed Findings", "", _render_items(finding_diff.added), "",
        "## Removed or Revised Confirmed Findings", "",
        _render_items(_render_revised(finding_diff.revised) + finding_diff.removed), "",
        "## New or Updated Tentative Hypotheses", "",
        _render_items(_render_revised(hypothesis_diff.revised) + hypothesis_diff.added), "",
    ])

    change_sections = (
        ("Important Decision Changes", "important_decisions", "Removed"),
        ("Failed / Blocked Attempt Changes", "failed_attempts", "Removed or Resolved"),
        ("Open Question Changes", "open_questions", "Removed or Resolved"),
        ("Next Action Changes", "next_actions", "Removed or Completed"),
    )
    for heading, field, removed_heading in change_sections:
        item_diff = alignment_for(field)
        added = _render_revised(item_diff.revised) + item_diff.added
        semantic_change_count += len(added) + len(item_diff.removed)
        lines.extend([
            f"## {heading}", "", "### Added", "", _render_items(added), "",
            f"### {removed_heading}", "", _render_items(item_diff.removed), "",
        ])

    if semantic_change_count == 0:
        lines.extend([
            "## Semantic Progress Note", "",
            "No semantic project progress detected; source changes appear to be rewording or equivalent restatements.",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"
