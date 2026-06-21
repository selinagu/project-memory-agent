# Project Memory Agent — v0.1 Prototype

Project Memory Agent is an early local CLI prototype for reconstructing and maintaining structured project state from files in a project folder. It scans local artifacts, parses supported formats, uses an LLM to extract validated `ProjectState` JSON, and renders human-readable checkpoint reports. The design and output formats are still changing.

## Current Pipeline

```text
raw project artifacts -> artifacts_index.json -> parsed_artifacts.json -> combined_notes.md with SOURCE markers -> project_state.json -> project_state_card.md -> checkpoint_summary.md -> latest/ and runs/<timestamp>/ checkpoint history
```

## Supported Artifact Types

- `.md`
- `.txt`
- `.log`
- `.csv`
- `.json`

The parsers are deterministic and perform conservative compression or structure extraction before content is sent to the LLM. For example, large logs and CSV files are summarized. They do not yet perform deep LLM-based experiment analysis.

## Setup

Create and activate a Python environment, then install the current dependencies:

```bash
pip install openai pydantic python-dotenv
```

Create a `.env` file in the repository root containing `OPENAI_API_KEY=your_api_key`.

## Run a Checkpoint

History mode creates a timestamped run and refreshes `latest/`:

```bash
python src/checkpoint.py \
  --project-dir data/projects/dflash_multi \
  --project-name dflash_multi \
  --base-output-dir outputs/checkpoints \
  --model gpt-4.1-mini
```

## Expected Output Structure

```text
outputs/checkpoints/dflash_multi/
  latest/
    artifacts_index.json
    parsed_artifacts.json
    combined_notes.md
    project_state.json
    project_state_card.md
    checkpoint_summary.md
  runs/
    <timestamp>/
      artifacts_index.json
      parsed_artifacts.json
      combined_notes.md
      project_state.json
      project_state_card.md
      checkpoint_summary.md
```

## Main Output Files

- `artifacts_index.json`: scanned artifact paths and metadata.
- `parsed_artifacts.json`: deterministic parsed representation of artifacts.
- `combined_notes.md`: LLM input assembled with source markers.
- `project_state.json`: validated structured project state.
- `project_state_card.md`: readable project state card.
- `checkpoint_summary.md`: short checkpoint overview and basic quality checks.

## Legacy Mode

The older direct output-directory mode still works:

```bash
python src/checkpoint.py \
  --project-dir data/projects/dflash_multi \
  --output-dir outputs/checkpoints/dflash_multi_legacy \
  --model gpt-4.1-mini
```

## Not Implemented Yet

- RAG or embeddings
- Web UI
- Autonomous multi-agent loop
- LLM-based artifact analysis layer
- Automatic diffs between checkpoints
