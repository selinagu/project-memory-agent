from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS = (
    REPO_ROOT / "src",
    REPO_ROOT / "benchmarks",
    REPO_ROOT / "demo",
    REPO_ROOT / "docs",
    REPO_ROOT / "README.md",
    REPO_ROOT / "PROJECT_STATUS.md",
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "MANIFEST.in",
)
TEXT_SUFFIXES = {
    ".cfg", ".csv", ".ini", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml",
}
SAFE_API_KEY_VALUES = {"", "your_api_key", "your-key-here", "<your_api_key>"}
RULES = (
    ("posix_home_path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/")),
    ("windows_user_path", re.compile(r"(?i)[A-Z]:[\\/]Users[\\/][^\\/\s]+[\\/]")),
    ("openai_token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
API_KEY_ASSIGNMENT = re.compile(
    r"OPENAI_API_KEY\s*=\s*([^\s#]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PrivacyFinding:
    rule: str
    path: str
    line: int


def _scan_text(text: str, label: str) -> list[PrivacyFinding]:
    findings: list[PrivacyFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in RULES:
            if pattern.search(line):
                findings.append(PrivacyFinding(rule, label, line_number))
        assignment = API_KEY_ASSIGNMENT.search(line)
        if assignment:
            value = assignment.group(1).strip("'\"")
            if value not in SAFE_API_KEY_VALUES and not value.startswith(("$", "<")):
                findings.append(
                    PrivacyFinding("openai_api_key_assignment", label, line_number)
                )
    return findings


def _decode(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _scan_file(path: Path, label: str) -> list[PrivacyFinding]:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"README", "LICENSE"}:
        return []
    try:
        text = _decode(path.read_bytes())
    except OSError:
        return [PrivacyFinding("unreadable_release_file", label, 0)]
    return _scan_text(text, label) if text is not None else []


def _scan_zip(path: Path, label: str) -> list[PrivacyFinding]:
    findings: list[PrivacyFinding] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if Path(name).suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = _decode(archive.read(name))
            if text is not None:
                findings.extend(_scan_text(text, f"{label}!{name}"))
    return findings


def _scan_tar(path: Path, label: str) -> list[PrivacyFinding]:
    findings: list[PrivacyFinding] = []
    with tarfile.open(path, "r:*") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            if not member.isfile() or Path(member.name).suffix.lower() not in TEXT_SUFFIXES:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            text = _decode(extracted.read())
            if text is not None:
                findings.extend(_scan_text(text, f"{label}!{member.name}"))
    return findings


def scan_release_paths(paths: Iterable[Path]) -> list[PrivacyFinding]:
    findings: list[PrivacyFinding] = []
    for requested in paths:
        path = requested.resolve()
        candidates = (
            sorted(item for item in path.rglob("*") if item.is_file())
            if path.is_dir()
            else [path]
        )
        for candidate in candidates:
            try:
                label = candidate.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                label = candidate.name
            try:
                if candidate.suffix == ".whl" or zipfile.is_zipfile(candidate):
                    findings.extend(_scan_zip(candidate, label))
                elif candidate.name.endswith((".tar.gz", ".tgz")):
                    findings.extend(_scan_tar(candidate, label))
                else:
                    findings.extend(_scan_file(candidate, label))
            except (OSError, tarfile.TarError, zipfile.BadZipFile):
                findings.append(PrivacyFinding("unreadable_release_archive", label, 0))
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when release files contain likely local paths or secrets."
    )
    parser.add_argument("paths", nargs="*", help="Files, directories, wheels, or sdists.")
    args = parser.parse_args()
    targets = [Path(value) for value in args.paths] if args.paths else list(DEFAULT_TARGETS)
    findings = scan_release_paths(targets)
    if findings:
        print(f"Release privacy: FAIL ({len(findings)} finding(s))")
        for finding in findings:
            location = f"{finding.path}:{finding.line}" if finding.line else finding.path
            print(f"- {finding.rule}: {location}")
        return 1
    print("Release privacy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
