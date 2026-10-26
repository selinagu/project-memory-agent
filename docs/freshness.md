# Git context and checkpoint freshness

PMA records bounded repository signals at checkpoint time and compares them
read-only later. Metadata describes repository state; it does not prove
semantic progress, completion, correctness, or intent.

## Checkpoint-time Git context

Every checkpoint writes `git_context.json` and a concise
`git_context.md`. Non-Git projects continue normally with an explicit
unavailable Git state.

Captured Git data is limited to:

- current branch or detached state;
- HEAD identity;
- working-tree status categories and bounded project-relative changed paths;
- schema-v2 fingerprints for Git-reported changed project files.

The prompt rendering is capped at 4,000 characters and 50 paths. It omits
repository roots, remotes, commit subjects, logs, diffs, file contents, raw Git
errors, and absolute paths.

Changed-file fingerprints contain byte size and SHA-256 digest. Missing files
and directories are represented without contents. Symlinks hash the encoded
link-target text and are never followed. Fingerprinting is independent of
scanner extensions and `pma.toml`, while generated checkpoint roots are
excluded.

For a project inside a larger Git repository, PMA excludes changes outside the
project and rewrites included paths relative to the project. Submodules may
appear as changed paths but are not recursively inspected.

## Evidence semantics

A changed path establishes only its Git status at checkpoint time. It cannot
establish implementation, progress, test results, decisions, deletion meaning,
or planned work. Repository facts may cite
`CHECKPOINT_METADATA: git_context.json`; project claims still require normal
`SOURCE` evidence.

Git metadata is excluded from `combined_notes.md` source lookup. `ask` and
`memo` treat it as a checkpoint snapshot, not live state.

## Freshness command

```bash
pma freshness --project-dir .
pma freshness --project-dir . --json
```

Custom storage uses the same resolver as checkpoint creation:

```bash
pma freshness \
  --project-dir ./research-project \
  --base-output-dir ./pma-data \
  --project-name experiment-a
```

The command returns:

| Status | Meaning |
|---|---|
| `current` | Available comparison signals still match |
| `stale` | At least one reliable signal changed |
| `unknown` | Available metadata cannot prove current or stale |
| `no_checkpoint` | No usable latest checkpoint was found |

These ordinary states exit with status 0. Automation should inspect the human
output or JSON `status` field.

## Git comparison

For Git projects, freshness compares repository availability, HEAD, branch or
detached state, changed-path categories, and schema-v2 fingerprints. A clean
schema-v1 checkpoint can still be confirmed current. A dirty schema-v1
checkpoint is `unknown` unless another signal proves it stale. Unhashable
directory-like changes are also handled conservatively as `unknown`.

## Non-Git comparison

Each new non-Git checkpoint stores `artifact_manifest.json` with logical
paths, bounded SHA-256 fingerprints, and a scanner-configuration fingerprint.
Freshness rebuilds the same manifest read-only to detect:

- selected-file additions and removals;
- selected-file content changes; and
- scanner-scope or budget configuration changes.

Legacy non-Git checkpoints without a manifest return `unknown`, never a false
`current`.

## Read-only boundary

Freshness does not update the checkpoint, create a run, write project files,
capture full diffs, call an LLM, or summarize changes since a previous commit.
See [ADR 0005](decisions/0005-freshness-signals.md) and the
[architecture freshness flow](architecture.md#freshness-path).
