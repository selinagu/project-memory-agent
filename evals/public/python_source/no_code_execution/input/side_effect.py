from pathlib import Path

Path("EXECUTED_SENTINEL").write_text("source was executed")


def safe_structure_only():
    return "FUNCTION_BODY_SENTINEL"
