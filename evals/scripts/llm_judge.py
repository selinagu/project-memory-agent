import json
import os
from typing import Any


JUDGE_SCHEMA_DESCRIPTION = """
Return valid JSON only with this shape:
{
  "status": "pass" | "fail" | "needs_review",
  "score": float from 0 to 1,
  "rationale": string,
  "passed_criteria": list[string],
  "failed_criteria": list[string],
  "uncertain_criteria": list[string]
}
"""


STATE_JUDGE_PROMPT = """You are an evaluation judge for Project Memory Agent.

Your task is to compare a generated project_state.json against a gold.yaml
semantic expectation file and decide whether the generated state is useful,
grounded, and semantically consistent.

General judging rules:
- Default judge mode evaluates semantic consistency between gold.yaml and the
  generated agent output. Do not independently invent requirements beyond
  gold.yaml.
- Treat semantically equivalent wording as acceptable. If a rule-based failure
  is only due to wording, abbreviation expansion, synonym, phrase order, or an
  equivalent paraphrase, mark that criterion as passed.
- Examples of semantic equivalence:
  - "Byte Pair Encoding (BPE) tokenizer" satisfies "BPE tokenizer".
  - "recovery after failed grasps" may satisfy "correction after failed
    grasps" when the intended meaning is the same.
  - "incremental pair-frequency update" may satisfy "incremental merge update"
    when the gold intent is making merge or pair-frequency updates incremental.
- Do not require exact keyword matches when the meaning is clearly present.
- Understand negation. A forbidden claim is a failure only if the generated
  state actually asserts it, not if it rejects or qualifies it.
- Use the rule-based failure details as debugging hints, not as binding truth.
  If the semantic match is clear, override the rule-based failure.
- If source notes are absent, do not complain about missing source context.
- If source notes are provided, use them only to verify grounding or resolve
  ambiguity.
- Penalize unsupported claims, hallucinations, and contradictions when they are
  visible from the provided inputs.
- Status policy:
  - Return "pass" when all substantive criteria are semantically satisfied,
    even if rule-based checks failed.
  - Return "fail" when substantive expected criteria are missing, forbidden
    claims are actually asserted, or there are clear unsupported/contradictory
    claims.
  - Return "needs_review" only for genuine ambiguity, partial satisfaction,
    missing support, unclear field placement, or when you cannot confidently
    decide.
- Output consistency policy:
  - If your rationale says a criterion is semantically satisfied, do not list
    that criterion in failed_criteria.
  - If there are no substantive failed or uncertain criteria, status must be
    "pass".
  - If status is "needs_review", uncertain_criteria should usually be non-empty
    or the rationale must explain the ambiguity.
- Be concise.

State-specific criteria:
- Does project_state capture the intended goal, stage, findings, hypotheses,
  open questions, next actions, and evidence?
- Are expected claims semantically present, even if field placement is slightly
  different but still reasonable?
- Are forbidden claims actually asserted?
- Are claims grounded in provided source artifacts?
- Are field placements reasonable? For example, a direct observed trade-off can
  be acceptable as a confirmed finding even if a brittle rule expected it
  elsewhere.
- Is the output useful as a project memory snapshot?

{schema}

gold.yaml as JSON:
{gold}

generated project_state.json:
{project_state}

rule-based failure details:
{rule_details}

combined_notes.md, if available:
{combined_notes}
"""


PROGRESS_JUDGE_PROMPT = """You are an evaluation judge for Project Memory Agent.

Your task is to compare a generated progress_since_last.md report against a
gold.yaml semantic expectation file and decide whether the progress report is
useful, grounded, and semantically consistent.

General judging rules:
- Default judge mode evaluates semantic consistency between gold.yaml and the
  generated agent output. Do not independently invent requirements beyond
  gold.yaml.
- Treat semantically equivalent wording as acceptable. If a rule-based failure
  is only due to wording, abbreviation expansion, synonym, phrase order, or an
  equivalent paraphrase, mark that criterion as passed.
- Examples of semantic equivalence:
  - "Byte Pair Encoding (BPE) tokenizer" satisfies "BPE tokenizer".
  - "recovery after failed grasps" may satisfy "correction after failed
    grasps" when the intended meaning is the same.
  - "incremental pair-frequency update" may satisfy "incremental merge update"
    when the gold intent is making merge or pair-frequency updates incremental.
- Do not require exact keyword matches when the meaning is clearly present.
- Understand negation. A forbidden claim is a failure only if the progress
  report actually asserts it, not if it rejects or qualifies it.
- Use the rule-based failure details as debugging hints, not as binding truth.
  If the semantic match is clear, override the rule-based failure.
- If source notes are absent, do not complain about missing source context.
- If source notes are provided, use them only to verify grounding or resolve
  ambiguity.
- Penalize unsupported claims, hallucinations, and contradictions when they are
  visible from the provided inputs.
- Status policy:
  - Return "pass" when all substantive criteria are semantically satisfied,
    even if rule-based checks failed.
  - Return "fail" when substantive expected criteria are missing, forbidden
    claims are actually asserted, or there are clear unsupported/contradictory
    claims.
  - Return "needs_review" only for genuine ambiguity, partial satisfaction,
    missing support, unclear change classification, or when you cannot
    confidently decide.
- Output consistency policy:
  - If your rationale says a criterion is semantically satisfied, do not list
    that criterion in failed_criteria.
  - If there are no substantive failed or uncertain criteria, status must be
    "pass".
  - If status is "needs_review", uncertain_criteria should usually be non-empty
    or the rationale must explain the ambiguity.
- Be concise.

Progress-specific criteria:
- Does progress_since_last.md report the actual semantic project changes?
- Does it avoid reporting wording-only changes as project progress?
- Does it classify added, revised, removed, and unchanged information
  reasonably?
- Does it avoid false confirmed-finding removals due to paraphrase?
- Does it avoid overinterpreting irrelevant artifact changes as project
  progress?

{schema}

gold.yaml as JSON:
{gold}

generated progress_since_last.md:
{progress_report}

rule-based failure details:
{rule_details}

combined_notes.md for v1, if available:
{combined_notes_v1}

combined_notes.md for v2, if available:
{combined_notes_v2}
"""


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


def _normalize_judge_result(data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("status")
    if status not in {"pass", "fail", "needs_review"}:
        status = "needs_review"

    try:
        score = float(data.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))

    return {
        "status": status,
        "score": score,
        "rationale": str(data.get("rationale", "")),
        "passed_criteria": list(data.get("passed_criteria", []) or []),
        "failed_criteria": list(data.get("failed_criteria", []) or []),
        "uncertain_criteria": list(data.get("uncertain_criteria", []) or []),
    }


def _call_judge(prompt: str, model: str) -> dict[str, Any]:
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "LLM judge requires openai and python-dotenv. "
            "Install with: pip install openai python-dotenv"
        ) from exc

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required when --judge is enabled.")

    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=prompt,
    )

    try:
        data = json.loads(_extract_json_text(response.output_text))
    except json.JSONDecodeError as exc:
        raise ValueError("Judge model did not return valid JSON.") from exc

    return _normalize_judge_result(data)


def judge_state_case(
    *,
    gold: dict[str, Any],
    project_state: dict[str, Any],
    rule_details: dict[str, Any] | None,
    combined_notes: str | None,
    model: str,
) -> dict[str, Any]:
    prompt = STATE_JUDGE_PROMPT.format(
        schema=JUDGE_SCHEMA_DESCRIPTION,
        gold=_json_dumps(gold),
        project_state=_json_dumps(project_state),
        rule_details=_json_dumps(rule_details or {}),
        combined_notes=combined_notes or "Not provided.",
    )
    return _call_judge(prompt=prompt, model=model)


def judge_progress_case(
    *,
    gold: dict[str, Any],
    progress_report: str,
    rule_details: dict[str, Any] | None,
    combined_notes_v1: str | None,
    combined_notes_v2: str | None,
    model: str,
) -> dict[str, Any]:
    prompt = PROGRESS_JUDGE_PROMPT.format(
        schema=JUDGE_SCHEMA_DESCRIPTION,
        gold=_json_dumps(gold),
        progress_report=progress_report,
        rule_details=_json_dumps(rule_details or {}),
        combined_notes_v1=combined_notes_v1 or "Not provided.",
        combined_notes_v2=combined_notes_v2 or "Not provided.",
    )
    return _call_judge(prompt=prompt, model=model)
