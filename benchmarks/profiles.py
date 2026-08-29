from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepositoryProfile:
    name: str
    generated_files: int
    lines_per_artifact: int

    @property
    def selected_artifacts(self) -> int:
        return self.generated_files - 5


PROFILES = {
    profile.name: profile
    for profile in (
        RepositoryProfile("tiny", 25, 16),
        RepositoryProfile("small", 100, 24),
        RepositoryProfile("medium", 500, 30),
        RepositoryProfile("large", 1_000, 30),
        RepositoryProfile("stress", 2_500, 12),
    )
}


def get_profile(name: str) -> RepositoryProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown benchmark profile {name!r}; expected one of "
            + ", ".join(PROFILES)
        ) from exc
