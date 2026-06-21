from artifacts import ArtifactIndex
from schemas import ProjectState


def bullet_list(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def build_quality_checks(state: ProjectState, artifact_index: ArtifactIndex) -> list[str]:
    checks: list[str] = []

    evidence_sources = {ev.source for ev in state.evidence}
    artifact_paths = {artifact.path for artifact in artifact_index.artifacts}

    if not state.evidence:
        checks.append("No evidence items were extracted.")

    unknown_sources = [
        source for source in evidence_sources
        if source not in artifact_paths
    ]
    if unknown_sources:
        checks.append(
            "Some evidence sources do not match scanned artifact paths: "
            + ", ".join(sorted(unknown_sources))
        )

    return checks


def render_checkpoint_summary(
    state: ProjectState,
    artifact_index: ArtifactIndex,
) -> str:
    artifact_lines = [
        f"- `{artifact.path}` ({artifact.artifact_type}, {artifact.size_bytes} bytes, {artifact.parser_status})"
        for artifact in artifact_index.artifacts
    ]

    strongly_supported_findings = state.confirmed_findings[:5]
    suggested_next_actions = state.next_actions[:5]
    quality_checks = build_quality_checks(state, artifact_index)

    return f"""# Checkpoint Summary: {state.project_name}

## Project Snapshot

{state.one_sentence_summary}

Current stage: {state.current_stage}

## Artifacts Scanned

{bullet_list(artifact_lines)}

## Key Findings

{bullet_list(strongly_supported_findings)}

## Open Questions

{bullet_list(state.open_questions)}

## Suggested Next Actions

{bullet_list(suggested_next_actions)}

## Quality Checks

{bullet_list(quality_checks)}
"""
