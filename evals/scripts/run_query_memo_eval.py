import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required for eval scripts. Install with: pip install pyyaml"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JUDGE_MODEL = "gpt-4.1-mini"


QUERY_MEMO_JUDGE_PROMPT = """You are an evaluation judge for Project Memory Agent query/memo evals.

Your task is to decide whether the actual output semantically satisfies the
public synthetic case expectations. Evaluate meaning and field boundaries, not
exact wording.

General judging rules:
- Use gold.yaml as the source of expected semantic constraints. Do not invent
  new requirements beyond the gold file.
- Treat equivalent wording and concise paraphrases as acceptable.
- Do not require exact sentence order unless chronology/order is the tested
  feature.
- Use rule check details as debugging hints, not as extra requirements.
- Penalize missing expected facts, asserted forbidden claims, hallucinated
  recommendations, unsupported source claims, and clear field-boundary errors.
- Do not penalize concise outputs if they satisfy the semantic constraints.

Field-boundary rules:
- Confirmed findings should not contain tentative or superseded conclusions as
  current facts.
- Tentative hypotheses should be clearly tentative.
- Open questions should not be converted into planned next actions.
- Planned next actions should be recorded/source-grounded, not invented.
- Historical progress may describe what happened during the reporting window,
  but latest ProjectState remains the current-state authority.
- Historical next actions should not become current planned actions unless they
  are latest ProjectState.next_actions.
- Corrections or supersessions should be described as evolution, not as
  simultaneous current findings.

Source and scope rules:
- If SOURCE snippets are cited, citations should use
  "combined_notes.md SOURCE <path>".
- The output should not imply direct raw artifact reads unless the command
  actually had such context.
- For group-update windows, respect visible last-N or since-date window
  semantics from gold and output.

Return valid JSON only with this shape:
{{
  "judge_passed": true | false,
  "reason": "short explanation",
  "issues": ["short issue", "..."]
}}

case_id:
{case_id}

capability:
{capability}

command as JSON:
{command}

gold.yaml as JSON:
{gold}

actual output:
{output}

rule check summary as JSON:
{rule_summary}
"""


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def discover_cases(eval_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    cases = []
    for gold_path in sorted(eval_root.rglob("gold.yaml")):
        gold = load_yaml(gold_path)
        if gold.get("case_type") == "query_memo":
            cases.append((gold_path, gold))
    return cases


def _json_dumps(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def _extract_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text.removeprefix("```json").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").strip()
    if text.endswith("```"):
        text = text.removesuffix("```").strip()
    return text


def markdown_section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    target = heading.strip().lower()
    start = None
    level = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() == target:
            start = index + 1
            level = len(stripped) - len(stripped.lstrip("#"))
            break
    if start is None:
        return ""

    end = len(lines)
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            next_level = len(stripped) - len(stripped.lstrip("#"))
            if next_level <= level:
                end = index
                break
    return "\n".join(lines[start:end])


def score_output(
    output: str,
    exit_code: int,
    gold: dict[str, Any],
    expected_exit_code: int | None = None,
) -> dict[str, Any]:
    passed = []
    failed = []
    lowered = output.lower()
    expected_exit = (
        int(expected_exit_code)
        if expected_exit_code is not None
        else int(gold.get("expected_exit_code", 0))
    )

    if exit_code == expected_exit:
        passed.append("exit_code")
    else:
        failed.append(
            f"exit_code: expected {expected_exit}, observed {exit_code}"
        )

    for text in gold.get("required_includes", []) or []:
        check = f"required_include: {text}"
        (passed if str(text).lower() in lowered else failed).append(check)

    for text in gold.get("forbidden_includes", []) or []:
        check = f"forbidden_include: {text}"
        (failed if str(text).lower() in lowered else passed).append(check)

    for heading in gold.get("required_sections", []) or []:
        check = f"required_section: {heading}"
        (passed if markdown_section(output, heading) else failed).append(check)

    for constraint in gold.get("section_constraints", []) or []:
        heading = constraint["section"]
        scoped = markdown_section(output, heading).lower()
        for text in constraint.get("required_includes", []) or []:
            check = f"section_required: {heading}: {text}"
            (passed if str(text).lower() in scoped else failed).append(check)
        for text in constraint.get("forbidden_includes", []) or []:
            check = f"section_forbidden: {heading}: {text}"
            (failed if str(text).lower() in scoped else passed).append(check)

    position = -1
    for text in gold.get("ordered_includes", []) or []:
        next_position = lowered.find(str(text).lower(), position + 1)
        check = f"ordered_include: {text}"
        if next_position < 0:
            failed.append(check)
        else:
            passed.append(check)
            position = next_position

    return {
        "passed": not failed,
        "score": len(passed) / (len(passed) + len(failed))
        if passed or failed
        else 1.0,
        "checks_passed": passed,
        "checks_failed": failed,
        "final_status": "pass" if not failed else "fail",
    }


def fixture_expected_exit_code(gold: dict[str, Any]) -> int:
    return int(gold.get("fixture_exit_code", gold.get("expected_exit_code", 0)))


def live_expected_exit_code(gold: dict[str, Any]) -> int:
    return int(gold.get("expected_exit_code", 0))


def command_with_project_dir(command: list[str], project_dir: Path) -> list[str]:
    if not command:
        raise ValueError("gold.yaml command must not be empty")

    updated = list(command)
    if updated[0] == "pma":
        updated = [sys.executable, "-m", "pma", *updated[1:]]

    project_dir_value = str(project_dir)
    for index, arg in enumerate(updated):
        if arg == "--project-dir":
            if index + 1 >= len(updated):
                raise ValueError("--project-dir is missing a value")
            updated[index + 1] = project_dir_value
            return updated
        if arg.startswith("--project-dir="):
            updated[index] = f"--project-dir={project_dir_value}"
            return updated

    insert_at = None
    for index, arg in enumerate(updated):
        if arg in {"ask", "memo"}:
            insert_at = index + 1
            break
    if insert_at is None:
        insert_at = len(updated)

    updated[insert_at:insert_at] = ["--project-dir", project_dir_value]
    return updated


def live_environment() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing}" if existing else src_path
    return env


def rule_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_passed": bool(result.get("passed")),
        "score": result.get("score"),
        "checks_passed": result.get("checks_passed", []),
        "checks_failed": result.get("checks_failed", []),
    }


def build_query_memo_judge_prompt(
    *,
    gold: dict[str, Any],
    output: str,
    result: dict[str, Any],
) -> str:
    return QUERY_MEMO_JUDGE_PROMPT.format(
        case_id=gold.get("case_id"),
        capability=gold.get("capability"),
        command=_json_dumps(gold.get("command")),
        gold=_json_dumps(gold),
        output=output,
        rule_summary=_json_dumps(rule_summary(result)),
    )


def parse_query_memo_judge_response(text: str) -> dict[str, Any]:
    try:
        data = json.loads(_extract_json_text(text))
    except json.JSONDecodeError as exc:
        return {
            "judge_passed": False,
            "judge_reason": "Judge model did not return valid JSON.",
            "judge_issues": [str(exc)],
        }

    if not isinstance(data, dict):
        return {
            "judge_passed": False,
            "judge_reason": "Judge JSON must be an object.",
            "judge_issues": [],
        }

    return {
        "judge_passed": bool(data.get("judge_passed")),
        "judge_reason": str(data.get("reason", "")),
        "judge_issues": [str(item) for item in data.get("issues", []) or []],
    }


def call_query_memo_judge(prompt: str, model: str) -> dict[str, Any]:
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Query/memo judge requires openai and python-dotenv. "
            "Install with: pip install openai python-dotenv"
        ) from exc

    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required when --judge is enabled.")

    client = OpenAI()
    response = client.responses.create(model=model, input=prompt)
    return parse_query_memo_judge_response(response.output_text)


def apply_query_memo_judge(
    *,
    result: dict[str, Any],
    gold: dict[str, Any],
    output: str,
    model: str,
) -> dict[str, Any]:
    rule_passed = bool(result.get("passed"))
    judged = dict(result)
    judged["rule_passed"] = rule_passed

    try:
        prompt = build_query_memo_judge_prompt(
            gold=gold,
            output=output,
            result=result,
        )
        judge_result = call_query_memo_judge(prompt, model)
    except Exception as exc:
        judge_result = {
            "judge_passed": False,
            "judge_reason": f"Judge failed: {exc}",
            "judge_issues": ["judge_error"],
        }

    judged.update(judge_result)
    judged["final_status"] = (
        "pass" if rule_passed and judged["judge_passed"] else "fail"
    )
    return judged


def run_fixture_case(gold_path: Path, gold: dict[str, Any]) -> dict[str, Any]:
    output_path = gold_path.parent / gold.get(
        "fixture_output",
        "fixture/stdout.md",
    )
    fixture_exit_code = fixture_expected_exit_code(gold)
    result = {
        "case_id": gold["case_id"],
        "case_type": gold["case_type"],
        "capability": gold.get("capability"),
        "evaluation_mode": "fixture",
        "command": gold.get("command"),
        "fixture_exit_code": fixture_exit_code,
        "output_path": str(output_path),
        "stdout_path": str(output_path),
    }
    try:
        output = output_path.read_text(encoding="utf-8")
        result.update(
            score_output(
                output,
                fixture_exit_code,
                gold,
                expected_exit_code=fixture_exit_code,
            )
        )
    except Exception as exc:
        result.update(
            {
                "passed": False,
                "score": 0.0,
                "checks_passed": [],
                "checks_failed": [f"runner_error: {exc}"],
                "final_status": "fail",
            }
        )
    return result


def failed_live_result(
    gold: dict[str, Any],
    case_output_dir: Path,
    command: list[str] | None,
    message: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
) -> dict[str, Any]:
    stdout_path = case_output_dir / "stdout.md"
    stderr_path = case_output_dir / "stderr.txt"
    command_path = case_output_dir / "command.json"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr or message, encoding="utf-8")
    command_path.write_text(
        json.dumps(command or gold.get("command"), indent=2),
        encoding="utf-8",
    )
    return {
        "case_id": gold["case_id"],
        "case_type": gold["case_type"],
        "capability": gold.get("capability"),
        "evaluation_mode": "live",
        "command": command,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "command_path": str(command_path),
        "exit_code": exit_code,
        "passed": False,
        "score": 0.0,
        "checks_passed": [],
        "checks_failed": [f"runner_error: {message}"],
        "final_status": "fail",
    }


def run_live_case(
    gold_path: Path,
    gold: dict[str, Any],
    run_root: Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    case_output_dir = run_root / gold["case_id"]
    case_output_dir.mkdir(parents=True, exist_ok=True)
    input_dir = gold_path.parent / "input"
    if not input_dir.is_dir():
        return failed_live_result(
            gold,
            case_output_dir,
            None,
            f"missing input directory: {input_dir}",
        )

    try:
        with tempfile.TemporaryDirectory(prefix=f"pma_{gold['case_id']}_") as temp_dir:
            temp_project = Path(temp_dir) / "project"
            shutil.copytree(input_dir, temp_project)
            command = command_with_project_dir(gold.get("command", []), temp_project)
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=live_environment(),
            )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return failed_live_result(
            gold,
            case_output_dir,
            locals().get("command"),
            f"command timed out after {timeout_seconds} seconds",
            stdout=stdout,
            stderr=stderr,
            exit_code=None,
        )
    except Exception as exc:
        return failed_live_result(
            gold,
            case_output_dir,
            locals().get("command"),
            str(exc),
        )

    stdout_path = case_output_dir / "stdout.md"
    stderr_path = case_output_dir / "stderr.txt"
    command_path = case_output_dir / "command.json"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    command_path.write_text(json.dumps(command, indent=2), encoding="utf-8")

    result = {
        "case_id": gold["case_id"],
        "case_type": gold["case_type"],
        "capability": gold.get("capability"),
        "evaluation_mode": "live",
        "command": command,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "command_path": str(command_path),
        "exit_code": completed.returncode,
    }
    result.update(
        score_output(
            completed.stdout,
            completed.returncode,
            gold,
            expected_exit_code=live_expected_exit_code(gold),
        )
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-root", default="evals/public")
    parser.add_argument("--output-root", default="evals/outputs")
    parser.add_argument(
        "--mode",
        choices=("fixture", "live"),
        default="fixture",
        help=(
            "fixture scores checked-in saved outputs without LLM calls; "
            "live executes each case command and may call the LLM."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--case-id",
        action="append",
        help="Run only the specified query/memo case id. Can be provided more than once.",
    )
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    args = parser.parse_args()

    eval_root = (REPO_ROOT / args.eval_root).resolve()
    output_root = (REPO_ROOT / args.output_root).resolve()
    run_root = output_root / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)
    results_path = run_root / "query_memo_results.jsonl"

    cases = discover_cases(eval_root)
    if args.case_id:
        requested = set(args.case_id)
        cases = [(path, gold) for path, gold in cases if gold.get("case_id") in requested]

    with results_path.open("w", encoding="utf-8") as results_file:
        for gold_path, gold in cases:
            if args.mode == "fixture":
                result = run_fixture_case(gold_path, gold)
            else:
                result = run_live_case(
                    gold_path,
                    gold,
                    run_root,
                    timeout_seconds=args.timeout_seconds,
                )
            if args.judge:
                output_path = result.get("stdout_path") or result.get("output_path")
                try:
                    output = Path(str(output_path)).read_text(encoding="utf-8")
                except Exception as exc:
                    output = ""
                    result["checks_failed"] = [
                        *result.get("checks_failed", []),
                        f"runner_error: could not read output for judge: {exc}",
                    ]
                    result["passed"] = False
                    result["final_status"] = "fail"
                result = apply_query_memo_judge(
                    result=result,
                    gold=gold,
                    output=output,
                    model=args.judge_model,
                )
            results_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"{result['case_id']}: {result['final_status'].upper()}")

    print(f"Results: {results_path}")


if __name__ == "__main__":
    main()
