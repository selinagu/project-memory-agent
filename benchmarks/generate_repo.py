from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import string

from benchmarks.profiles import PROFILES, RepositoryProfile, get_profile


ARTIFACT_EXTENSIONS = (
    ".md", ".md", ".md", ".md", ".md", ".md", ".md", ".md",
    ".txt", ".txt", ".txt", ".txt",
    ".json", ".json", ".json",
    ".csv", ".csv",
    ".log", ".log",
    ".py",
)
AUXILIARY_PATHS = (
    "pma.toml",
    ".env",
    ".project_memory/latest/generated.md",
    "node_modules/generated.md",
    "assets/unsupported.bin",
)


@dataclass(frozen=True)
class GeneratedRepository:
    profile: str
    seed: int
    generated_files: int
    expected_selected_artifacts: int
    approximate_loc: int
    selected_raw_bytes: int
    content_digest: str
    artifact_type_counts: dict[str, int]


def _random_words(randomizer: random.Random, count: int) -> list[str]:
    alphabet = string.ascii_lowercase
    return [
        "".join(randomizer.choice(alphabet) for _ in range(8))
        for _ in range(count)
    ]


def _content_for(
    extension: str,
    index: int,
    lines: int,
    randomizer: random.Random,
) -> str:
    words = _random_words(randomizer, max(lines * 3, 12))
    if extension == ".md":
        rendered = [f"# Synthetic artifact {index:05d}"]
        rendered.extend(
            f"- finding {line:03d}: {' '.join(words[line * 3:line * 3 + 3])}"
            for line in range(lines - 1)
        )
        return "\n".join(rendered) + "\n"
    if extension == ".txt":
        return "\n".join(
            f"note {index:05d}-{line:03d} {' '.join(words[line * 3:line * 3 + 3])}"
            for line in range(lines)
        ) + "\n"
    if extension == ".log":
        levels = ("INFO", "INFO", "WARNING", "ERROR")
        return "\n".join(
            f"{levels[line % len(levels)]} event={index:05d}-{line:03d} "
            f"detail={'-'.join(words[line * 3:line * 3 + 3])}"
            for line in range(lines)
        ) + "\n"
    if extension == ".csv":
        rows = ["row_id,value,label"]
        rows.extend(
            f"{line},{index * 1000 + line},{words[line]}"
            for line in range(max(lines - 1, 1))
        )
        return "\n".join(rows) + "\n"
    if extension == ".json":
        value = {
            "artifact_id": index,
            "records": [
                {
                    "row": line,
                    "value": index * 1000 + line,
                    "label": words[line],
                }
                for line in range(max(lines // 4, 1))
            ],
        }
        return json.dumps(value, indent=2, sort_keys=True) + "\n"
    if extension == ".py":
        definitions = max(1, min(lines // 4, 8))
        rendered = [
            '"""Synthetic benchmark module."""',
            "from __future__ import annotations",
            "",
        ]
        for number in range(definitions):
            rendered.extend(
                [
                    f"def operation_{number}(value: int, label: str = 'redacted') -> int:",
                    f"    internal_value = {index + number}",
                    "    return value + internal_value",
                    "",
                ]
            )
        return "\n".join(rendered)
    raise ValueError(f"unsupported synthetic extension: {extension}")


def _scanner_config(profile: RepositoryProfile) -> str:
    max_artifacts = max(profile.selected_artifacts, 500)
    return (
        "[scanner]\n"
        "include_python = true\n"
        f"max_artifacts = {max_artifacts}\n"
        "max_non_python_file_bytes = 1048576\n"
        "max_total_source_bytes = 104857600\n"
        "max_combined_notes_chars = 2000000\n"
    )


def generate_repository(
    target: Path,
    profile: RepositoryProfile,
    *,
    seed: int,
) -> GeneratedRepository:
    if type(seed) is not int or seed < 0:
        raise ValueError("benchmark seed must be a non-negative integer")
    target.mkdir(parents=True, exist_ok=False)
    randomizer = random.Random(seed)
    digest = hashlib.sha256()
    approximate_loc = 0
    selected_raw_bytes = 0
    type_counts: dict[str, int] = {}

    for index in range(profile.selected_artifacts):
        extension = ARTIFACT_EXTENSIONS[index % len(ARTIFACT_EXTENSIONS)]
        relative = Path(
            f"layer_{index % 10:02d}",
            f"group_{(index // 10) % 10:02d}",
            f"artifact_{index:05d}{extension}",
        )
        content = _content_for(
            extension,
            index,
            profile.lines_per_artifact,
            randomizer,
        )
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        raw = content.encode("utf-8")
        digest.update(relative.as_posix().encode("utf-8") + b"\0" + raw)
        approximate_loc += len(content.splitlines())
        selected_raw_bytes += len(raw)
        type_counts[extension] = type_counts.get(extension, 0) + 1

    (target / "pma.toml").write_text(_scanner_config(profile), encoding="utf-8")
    (target / ".env").write_text("SYNTHETIC_PLACEHOLDER=unused\n", encoding="utf-8")
    generated = target / ".project_memory" / "latest" / "generated.md"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated checkpoint content\n", encoding="utf-8")
    dependency = target / "node_modules" / "generated.md"
    dependency.parent.mkdir()
    dependency.write_text("generated dependency content\n", encoding="utf-8")
    unsupported = target / "assets" / "unsupported.bin"
    unsupported.parent.mkdir()
    unsupported.write_bytes(b"synthetic-binary-placeholder")

    return GeneratedRepository(
        profile=profile.name,
        seed=seed,
        generated_files=profile.generated_files,
        expected_selected_artifacts=profile.selected_artifacts,
        approximate_loc=approximate_loc,
        selected_raw_bytes=selected_raw_bytes,
        content_digest=digest.hexdigest(),
        artifact_type_counts=dict(sorted(type_counts.items())),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic PMA benchmark repository."
    )
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generated = generate_repository(
        args.output,
        get_profile(args.profile),
        seed=args.seed,
    )
    print(json.dumps(generated.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
