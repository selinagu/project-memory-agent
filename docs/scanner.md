# Scanner safety and configuration

PMA scans a bounded set of project artifacts. Scanner policy is explicit and
does not treat `.gitignore` as the safety contract.

## Supported artifacts

The scanner accepts:

- `.md`
- `.txt`
- `.log`
- `.csv`
- `.json`
- `.py`, only when `[scanner].include_python = true`

Built-in rules exclude secrets, caches, generated/private areas, checkpoint
output, unsupported types, and symbolic links. When checkpoint storage is
inside the tracked project, the entire resolved output root is excluded before
user patterns are evaluated. External storage does not change logical artifact
labels or expose its absolute path.

## `pma.toml`

Place an optional `pma.toml` in the directory passed to `--project-dir`:

```toml
[scanner]
include_python = true
include = ["README.md", "docs/**/*.md", "results/**/*.json", "src/**/*.py"]
exclude = ["results/debug/**", "archive/**"]
max_artifacts = 500
max_non_python_file_bytes = 1048576
max_total_source_bytes = 10485760
max_combined_notes_chars = 250000
```

Without the file, default scanner behavior is unchanged. A non-empty `include`
list restricts selection; `exclude` is applied afterward. Empty or absent
lists add no restriction.

Patterns use POSIX-style project-relative paths. `**` matches zero or more
segments, so `docs/**/*.md` includes files directly under `docs/` and in
nested directories. User patterns cannot override built-in ignores or expand
the supported extension list.

Malformed configuration, unknown sections, unknown keys, or invalid values
stop checkpoint construction before publication.

## Resource budgets

The default configurable limits are:

| Budget | Default |
|---|---:|
| Selected artifacts | 500 |
| Bytes per non-Python file | 1,048,576 |
| Total selected source bytes | 10,485,760 |
| Combined-note characters | 250,000 |

Values must be positive integers; booleans are rejected. Configured values
cannot exceed built-in hard ceilings. Artifact count, per-file size, and total
bytes are checked before extraction. Combined-note size is checked before any
OpenAI call. Python files retain the stricter 262,144-byte extraction limit.

## Opt-in Python structure

`include_python = true` is required. An include glob ending in `.py` does
not enable Python scanning by itself. Enabled files still pass through
include/exclude patterns, built-in ignores, size checks, symlink rejection, and
checkpoint-root exclusion.

PMA uses the standard-library AST parser and never imports, executes, evaluates,
or launches scanned Python code. A structural preview may contain:

- a bounded module-docstring summary;
- top-level imported module names and statically declared `__all__` names;
- public top-level classes and functions;
- class bases and public methods;
- parameter names and kinds; and
- safe type annotations.

It excludes function bodies, module constants, decorator arguments, ordinary
string literals, actual default values, and private or dunder definitions.
Defaults and literal annotation values are rendered as `...`.

The deterministic preview limits are:

- 262,144 bytes per Python file
- 4,000 characters per preview
- 240 characters for the module-docstring summary
- 20 top-level imports
- 40 public top-level definitions
- 20 public methods per class

Syntax, decoding, size, read, and symlink failures produce a bounded status
without source content or tracebacks. Failed Python artifacts are omitted from
`combined_notes.md`; other safe artifacts continue.

## Evidence boundary

Successful artifacts retain project-relative `SOURCE` markers in derived
checkpoint memory. Scanner selection does not authorize arbitrary later access
to raw files: `ask` and `memo` consume the checkpoint and bounded excerpts.
See [ADR 0006](decisions/0006-opt-in-python-awareness.md) and the
[architecture](architecture.md).
