from artifacts import ParsedArtifactBundle
from schemas import ProjectState


def _render_items(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def _artifact_hashes(bundle: ParsedArtifactBundle) -> dict[str, str]:
    return {
        artifact.path: artifact.content_hash
        for artifact in bundle.artifacts
    }


def render_progress_since_last(
    old_state: ProjectState | None,
    new_state: ProjectState,
    old_parsed_artifacts: ParsedArtifactBundle | None = None,
    new_parsed_artifacts: ParsedArtifactBundle | None = None,
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
            path
            for path in old_hashes.keys() & new_hashes.keys()
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
            "### Added Artifacts",
            "",
            _render_items(added_artifacts),
            "",
            "### Removed Artifacts",
            "",
            _render_items(removed_artifacts),
            "",
            "### Changed Source Artifacts",
            "",
            _render_items(modified_artifacts),
            "",
        ])

    new_findings = [
        item
        for item in new_state.confirmed_findings
        if item not in old_state.confirmed_findings
    ]
    removed_findings = [
        item
        for item in old_state.confirmed_findings
        if item not in new_state.confirmed_findings
    ]
    new_hypotheses = [
        item
        for item in new_state.tentative_hypotheses
        if item not in old_state.tentative_hypotheses
    ]

    lines.extend([
        "## Current Snapshot",
        "",
        f"Current stage: {new_state.current_stage}",
        "",
        "## New Confirmed Findings",
        "",
        _render_items(new_findings),
        "",
        "## Removed or Revised Confirmed Findings",
        "",
        _render_items(removed_findings),
        "",
        "## New or Updated Tentative Hypotheses",
        "",
        _render_items(new_hypotheses),
        "",
    ])

    change_sections = (
        (
            "Important Decision Changes",
            new_state.important_decisions,
            old_state.important_decisions,
            "Removed",
        ),
        (
            "Failed / Blocked Attempt Changes",
            new_state.failed_attempts,
            old_state.failed_attempts,
            "Removed or Resolved",
        ),
        (
            "Open Question Changes",
            new_state.open_questions,
            old_state.open_questions,
            "Removed or Resolved",
        ),
        (
            "Next Action Changes",
            new_state.next_actions,
            old_state.next_actions,
            "Removed or Completed",
        ),
    )

    for heading, new_items, old_items, removed_heading in change_sections:
        added = [item for item in new_items if item not in old_items]
        removed = [item for item in old_items if item not in new_items]
        lines.extend([
            f"## {heading}",
            "",
            "### Added",
            "",
            _render_items(added),
            "",
            f"### {removed_heading}",
            "",
            _render_items(removed),
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"
