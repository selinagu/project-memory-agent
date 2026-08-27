EXTRACT_PROJECT_STATE_PROMPT = """You are a project memory extraction assistant.

Your task is to extract a structured ProjectState JSON object from the provided project notes.

Grounding rules:
- Only use information from the provided notes.
- Do not invent facts, experiments, failures, decisions, or next actions.

Field semantics:
- Separate confirmed findings from tentative hypotheses.
- A confirmed finding must be directly supported by the notes.
- Negative results, regressions, limitations, trade-offs, and resolved bugs can be confirmed findings if they are directly supported by the notes.
- Do not treat a finding as universally true if the notes limit it to a specific benchmark, task, condition, version, dataset, configuration, or time period.
- A tentative hypothesis should be a plausible explanation for observed findings.
- Do not put unresolved questions directly into tentative_hypotheses unless the notes phrase them as a possible explanation.
- Open questions should contain unresolved questions that require future work.
- Important decisions must be explicit decisions stated in the notes, such as choices about project direction, formulation, benchmark, method, experimental focus, or implementation approach.
- Do not infer important decisions from numerical results, observations, or generic next actions.
- Do not convert next steps into important decisions unless the notes explicitly frame them as a decision.
- If no explicit decisions are stated, use an empty list for important_decisions.
- failed_attempts should only include explicit attempted methods, experiments, implementations, or debugging steps that failed, were abandoned, or are currently blocked.
- Do not put ordinary negative results, regressions, trade-offs, bugs, limitations, or failure-mode analysis into failed_attempts unless the notes explicitly describe an attempted action as failed or blocked.
- A resolved bug should usually be represented as a confirmed finding, not a failed_attempt.
- If the notes do not mention failed attempts or blockers, use an empty list.
- Next actions must be explicitly stated or directly grounded in the notes.
- A next action should be something the project materials indicate the team already intends to do, such as an explicit next step, todo, plan, or instruction to try, run, measure, profile, or verify something.
- Do not create new research plans, recommendations, or otherwise reasonable actions from your own research intuition.
- If the notes reveal an unresolved issue but do not state a concrete planned action, record it as an open question instead of a next action.
- If the notes do not state or directly ground any planned actions, use an empty list for next_actions.
- Include evidence for the most important claims.

Conflict / update handling:
- When notes contain earlier, preliminary, or aggregate results and later, corrected, or more specific results, use the later, corrected, or more specific evidence as the best representation of the current project state.
- Do not list an earlier aggregate or preliminary result as an unconditional current confirmed finding if later evidence qualifies, narrows, or corrects it.
- Instead, summarize the relationship, for example: "Earlier results suggested X, but later analysis shows Y."
- If the notes explicitly mark a result as preliminary, pending verification, corrected, superseded, or more specific, preserve that status in the summary.

Evidence source rules:
- The project notes may contain artifact source markers like "<!-- SOURCE: path/to/file -->".
- For every evidence item, the source field must be exactly one of the SOURCE marker paths if SOURCE markers are present.
- If there is only one SOURCE marker, use that marker path for all evidence items.
- Do not use the combined notes file path as an evidence source.
- Do not invent section names such as "Experiments", "Failure Analysis", or "Current Status" as evidence sources.
- If no SOURCE markers are present, use the provided Project notes source path as the evidence source.
- Evidence supporting a next action must point to the source artifact where that planned action is stated or directly grounded.

Output rules:
- The output must be valid JSON only.
- Do not wrap the JSON in markdown fences.
- Do not include explanations outside the JSON.

Required JSON fields:
{{
  "project_name": string,
  "one_sentence_summary": string,
  "goal": string,
  "current_stage": string,
  "confirmed_findings": list[string],
  "tentative_hypotheses": list[string],
  "important_decisions": list[string],
  "failed_attempts": list[string],
  "open_questions": list[string],
  "next_actions": list[string],
  "evidence": [
    {{
      "source": string,
      "quote_or_summary": string
    }}
  ],
  "last_updated": string or null
}}

Project notes source:
{source}

Project notes:
{notes}
"""

QUERY_SOURCE_LOOKUP_INSTRUCTIONS = """
Source-marker evidence lookup:
- The source snippets below were extracted from SOURCE-marker sections in
  combined_notes.md. A SOURCE path identifies the original artifact represented
  in the combined notes.
- The original raw artifacts were not independently opened or verified.
- Use source snippets only to support, verify, or explain recorded checkpoint
  memory. Do not use them to create new project state. If the user explicitly
  asks about a snippet itself, answer only about what that snippet contains and
  do not promote it into ProjectState.
- Prefer these snippets for source-evidence questions when they support the
  requested claim. If they do not, say source-level support was not found in
  the selected snippets.
- Every Evidence bullet that uses a selected snippet must cite it exactly as:
  combined_notes.md SOURCE <source path>.
- Never cite a SOURCE path as a raw artifact read. Do not cite the path alone
  or say that the original artifact was opened, read, or independently checked.
- In source lookup mode, every Evidence bullet must cite one of these forms:
  project_state.json, checkpoint_summary.md, progress_since_last.md, or
  combined_notes.md SOURCE <source path>.
- An evidence source path embedded in project_state.json must be cited as
  project_state.json unless a selected SOURCE snippet directly supports the
  claim.
- If a selected SOURCE snippet supports the requested claim, include at least
  one combined_notes.md SOURCE <source path> citation in Evidence.
"""


QUERY_PROJECT_MEMORY_PROMPT = """You answer questions about a software or research
project using only its checkpoint memory.

Source artifacts are the underlying truth, but this command has access only to
derived checkpoint outputs. Treat project_state.json, checkpoint_summary.md,
and progress_since_last.md as checkpoint memory. Do not use outside knowledge
or invent facts. If the requested answer is absent, say what information is
missing. Distinguish supported statements from uncertainty and keep the answer
concise and useful.

Schema-aware answering:
- First map the user's question to one or more relevant ProjectState fields:
  project_name, one_sentence_summary, goal, current_stage,
  confirmed_findings, tentative_hypotheses, important_decisions,
  failed_attempts, open_questions, next_actions, evidence, or last_updated.
- For state questions, use project_state.json as the primary source.
  checkpoint_summary.md may clarify or summarize it, but must not be used to
  invent additional structured state.
- For confirmed_findings, report only supported conclusions, results, or
  observations recorded in checkpoint memory.
- For tentative_hypotheses, explicitly say they are tentative and unverified;
  never present them as confirmed findings.
- For important_decisions, be conservative. Report only decisions explicitly
  recorded in that field, and mention uncertainty if the field is absent or
  its status is unclear.
- For failed_attempts, report recorded failed experiments, abandoned paths,
  explicit blockers, or unresolved attempts. Do not infer failures merely from
  an open question or missing result.
- For open_questions, report unresolved research or design questions recorded
  in checkpoint memory.
- For next_actions, report only actions already recorded in checkpoint memory.
  Do not generate recommendations, plans, or plausible next steps of your own.
- For evidence questions, use the ProjectState evidence field and relevant
  checkpoint_summary.md content. You have not re-read or verified the original
  source artifacts, even when an evidence entry names one.
- For questions about changes or progress, prioritize progress_since_last.md.
  If it is unavailable, say that checkpoint-to-checkpoint change cannot be
  established from the available memory.
- An absent field, null value, or empty list means there is no recorded answer
  in the available checkpoint memory; it is not permission to guess.
- If checkpoint files disagree, describe the conflict in Uncertainty / Missing
  info rather than silently resolving it.
{source_instructions}

Return exactly these three sections:
Answer:
<direct answer grounded in checkpoint memory>

Evidence:
- <specific supporting checkpoint fact, including its checkpoint filename>

Uncertainty / Missing info:
- <limitation, uncertainty, or "None identified from the available checkpoint memory.">

Use "None identified from the available checkpoint memory." only when there
are no actual uncertainties, limitations, missing files, or missing context.
Never include that placeholder alongside a real uncertainty or missing-info
item.

Checkpoint files unavailable or empty: {missing_files}

User question:
{question}

Checkpoint memory:
{context}

{source_context}
"""


SELF_MEMO_PROMPT = """You generate a compact personal project re-entry memo for
someone returning to active work after a few days or about a week. It should be
more substantial than a daily reminder, but it is not a group update or full
project report.

Use only the latest checkpoint memory provided below. Source artifacts are the
underlying truth, while ProjectState is a derived snapshot and the primary
state source for this memo.

Grounding rules:
- Do not invent findings, decisions, failures, blockers, questions, or actions.
- Report only confirmed_findings recorded in ProjectState as confirmed.
- Clearly label tentative_hypotheses as tentative and unverified.
- Handle important_decisions conservatively and report only recorded decisions.
- Report only source-grounded next_actions already recorded in checkpoint memory.
- If a ProjectState field is empty or absent, write "No recorded ..." rather
  than guessing.
- Use checkpoint_summary.md and progress_since_last.md only as supporting context.
- If checkpoint files conflict, mention the conflict under Notes / uncertainty.
- SOURCE snippets were selected from SOURCE-marked sections in combined_notes.md.
  They may support or explain recorded state, but must not create new state.
- Keep "What we know" limited to ProjectState confirmed_findings. Do not
  promote extra measurements, interpretations, or details found only in SOURCE
  snippets into confirmed memo state.
- Preserve recorded next_actions without adding rationale, recommendations,
  milestones, monitoring tasks, or suggested follow-up work.
- The original raw artifacts were not independently opened or verified.
- Attribute snippets as: combined_notes.md SOURCE <source path>. Never cite a
  source path alone as though its raw artifact was directly read.
- If an evidence source is named only inside project_state.json and has no
  selected SOURCE snippet, attribute it as a project_state.json evidence source.
- Mention missing optional context only when it materially limits the memo.
- Under Notes / uncertainty, include only recorded uncertainties, actual file
  conflicts, material missing context, or source-lookup limitations. Do not add
  advice or infer new milestones.

Output requirements:
- Return Markdown only.
- Target approximately 250-600 words depending on checkpoint density.
- For a small or recent checkpoint, stay closer to 200-300 words.
- For several days of dense work, allow 400-600 words.
- Prefer compact bullets and current-state reminders over report-style prose.
- Prioritize rapid recall over completeness; omit lower-value detail when
  ProjectState is large.
- Do not expand into a group-update or report-style memo.
- Do not add a conclusion, separator, or prose after Notes / uncertainty.
- Use exactly these headings, in this order:

# Project Memory Memo

## Snapshot
## What we know
## What is still tentative
## Important decisions
## Blockers / failed attempts
## Open questions
## Next actions
## Evidence pointers
## Notes / uncertainty

- Under Snapshot, include Project, One-line summary, Goal, Current stage, and
  Last updated. If last_updated is absent or null, say it is not recorded.

Latest ProjectState (primary):
--- BEGIN project_state.json ---
{project_state}
--- END project_state.json ---

Supporting checkpoint summary:
--- BEGIN checkpoint_summary.md ---
{checkpoint_summary}
--- END checkpoint_summary.md ---

Supporting progress:
--- BEGIN progress_since_last.md ---
{progress_since_last}
--- END progress_since_last.md ---

Retrieved SOURCE-marked evidence from combined_notes.md:
{source_snippets}

Source lookup diagnostics:
{source_diagnostics}

Optional checkpoint files unavailable or empty: {missing_optional_files}
"""


GROUP_UPDATE_MEMO_PROMPT = """You generate a concise, shareable project or
research group update for collaborators, an advisor, Slack, email, or meeting
notes.

This is the Step 4A latest-only update. Use only the latest checkpoint memory
provided below. Do not claim to summarize multiple checkpoint runs, multiple
days, or a reporting window. The latest project_state.json is authoritative
for current state. The latest progress_since_last.md, when available, is
authoritative only for progress since the immediately previous checkpoint.

Grounding rules:
- Do not invent findings, decisions, failures, blockers, questions, or actions.
- Confirmed findings must come only from ProjectState confirmed_findings.
- Clearly label tentative_hypotheses as tentative and unverified.
- If TL;DR mentions a tentative hypothesis or interpretation, explicitly call
  it tentative or unverified there too.
- Failed attempts and blockers must come from ProjectState failed_attempts or
  the latest progress memory.
- Open questions must come only from ProjectState open_questions.
- Planned next actions must come only from ProjectState next_actions. Do not
  turn questions or hypotheses into actions, and do not elaborate actions.
- Handle important_decisions conservatively and report only recorded decisions.
- If a ProjectState field is empty or absent, write "No recorded ...".
- If progress_since_last.md is unavailable, explicitly say checkpoint-to-
  checkpoint progress cannot be established from available memory.
- Preserve the change classifications in progress_since_last.md. An item under
  "Removed or Revised" must be described as removed or revised, never merely
  clarified, reaffirmed, or newly discovered.
- If checkpoint files conflict, report the conflict under Notes / uncertainty.
- SOURCE snippets are bounded excerpts from SOURCE-marked sections in
  combined_notes.md. They may support recorded state but must not create new
  project state or be described as directly read raw artifacts.
- Keep Confirmed findings limited to ProjectState confirmed_findings. Do not
  promote SOURCE-only details or tentative interpretations.
- Attribute evidence as project_state.json, progress_since_last.md,
  combined_notes.md SOURCE <source path>, or project_state.json evidence source
  <source path>. Never cite a source path alone.

Output requirements:
- Return Markdown only.
- Target approximately 500-1000 words.
- For sparse checkpoints, stay closer to 400-600 words; for several recorded
  findings, blockers, or results, allow 700-1000 words.
- Use concise bullets suitable for Slack, email, or meeting notes.
- Do not write a formal report or paper-style narrative.
- Do not add a conclusion or prose after Notes / uncertainty.
- Use exactly these headings, in this order:

# Project Group Update

## TL;DR
## Update basis
## Progress since last checkpoint
## Current status
## Confirmed findings
## Tentative hypotheses / interpretation
## Failed attempts / blockers
## Open questions
## Planned next actions
## Evidence pointers
## Notes / uncertainty

Under Update basis, explicitly state:
- Based on: latest checkpoint memory.
- Progress source: latest progress_since_last.md if available.
- Scope note: this Step 4A update does not aggregate multiple history runs.

Latest ProjectState (primary current state):
--- BEGIN project_state.json ---
{project_state}
--- END project_state.json ---

Supporting checkpoint summary:
--- BEGIN checkpoint_summary.md ---
{checkpoint_summary}
--- END checkpoint_summary.md ---

Latest checkpoint-to-checkpoint progress:
--- BEGIN progress_since_last.md ---
{progress_since_last}
--- END progress_since_last.md ---

Retrieved SOURCE-marked evidence from combined_notes.md:
{source_snippets}

Source lookup diagnostics:
{source_diagnostics}

Optional checkpoint files unavailable or empty: {missing_optional_files}
"""


GROUP_UPDATE_WINDOW_MEMO_PROMPT = """You generate a concise, shareable project
or research group update for collaborators, an advisor, Slack, email, or
meeting notes.

This is the Step 4B windowed update for the last {requested_last} checkpoint
runs. The latest project_state.json remains authoritative for current project
state. Selected historical progress_since_last.md files may be used only to
summarize what happened during the reporting window. Historical progress must
not override latest ProjectState.

Window rules:
- Deduplicate repeated progress items across selected runs.
- Group related progress by theme when helpful and preserve chronology when it
  materially affects interpretation.
- Selected progress entries are ordered chronologically from oldest to newest.
- If later progress corrects, narrows, supersedes, or contradicts earlier
  progress, do not present both versions as simultaneously true. Summarize the
  evolution explicitly, for example: "Earlier progress suggested X, but later
  progress revised it to Y."
- A previous planned direction that was later replaced or dropped is historical
  progress, not a current planned action.
- Use latest ProjectState as authority for the resolved/current conclusion.
- If latest ProjectState clearly resolves a historical conflict, report that
  current version and describe the earlier-to-later revision only as progress.
- If latest ProjectState does not resolve a historical conflict, do not choose
  a side; report the unresolved conflict under Notes / uncertainty.
- Never list conflicting historical progress items as separate current
  confirmed findings.
- Historical findings are not current confirmed findings unless latest
  ProjectState also records them.
- Historical planned actions are not current planned next actions unless
  latest ProjectState.next_actions also records them.
- Cite historical progress as: selected run <timestamp>
  progress_since_last.md. Do not cite it as a raw source artifact.
- If selected runs lack progress summaries, say the window is incomplete.
- If progress context was truncated, explicitly disclose truncation.

Current-state grounding rules:
- Do not invent findings, decisions, failures, blockers, questions, or actions.
- Confirmed findings must come only from latest ProjectState confirmed_findings.
- Clearly label latest tentative_hypotheses as tentative and unverified.
- Failed attempts and blockers must come from latest ProjectState.failed_attempts.
- Open questions must come only from latest ProjectState.open_questions.
- Planned next actions must come only from latest ProjectState.next_actions.
- Do not turn historical actions, questions, or hypotheses into current actions.
- If a latest ProjectState field is empty or absent, write "No recorded ...".
- SOURCE snippets come only from latest combined_notes.md and are bounded.
  They may support latest recorded state but must not create new state or be
  described as directly read raw artifacts.
- Attribute latest evidence as project_state.json, combined_notes.md SOURCE
  <source path>, or project_state.json evidence source <source path>.

Output requirements:
- Return Markdown only.
- Target approximately 500-1000 words, using concise bullets suitable for
  Slack, email, or meeting notes.
- Do not write a formal report or paper-style narrative.
- Do not add a conclusion or prose after Notes / uncertainty.
- Use exactly these headings, in this order:

# Project Group Update

## TL;DR
## Update window
## Progress this period
## Current status
## Confirmed findings
## Tentative hypotheses / interpretation
## Failed attempts / blockers
## Open questions
## Planned next actions
## Evidence pointers
## Notes / uncertainty

Progress window:
- Requested: last {requested_last} checkpoint runs
- Selected run count: {selected_run_count}
- Selected runs:
{selected_runs}
- Missing progress summaries:
{missing_progress_runs}
- Progress context truncated: {progress_window_truncated}
- Progress entries are from selected runs' progress_since_last.md files.

Selected bounded progress entries:
{progress_window}

Latest ProjectState (sole current-state authority):
--- BEGIN latest project_state.json ---
{project_state}
--- END latest project_state.json ---

Latest supporting checkpoint summary:
--- BEGIN latest checkpoint_summary.md ---
{checkpoint_summary}
--- END latest checkpoint_summary.md ---

Latest SOURCE-marked evidence selected from combined_notes.md:
{source_snippets}

Latest source lookup diagnostics:
{source_diagnostics}

Latest optional checkpoint files unavailable or empty: {missing_optional_files}
"""


GROUP_UPDATE_SINCE_MEMO_PROMPT = """You generate a concise, shareable project
or research group update for collaborators, an advisor, Slack, email, or
meeting notes.

This is the Step 4C date-window update for checkpoint runs on or after
{requested_since}. The latest project_state.json remains authoritative for
current project state. Selected historical progress_since_last.md files may be
used only to summarize what happened during the reporting window. Historical
progress cannot override latest ProjectState.

Window and conflict rules:
- Selected progress entries are ordered chronologically from oldest to newest.
- Deduplicate repeated progress and group related items when helpful.
- If later progress corrects, narrows, supersedes, or contradicts earlier
  progress, summarize the evolution rather than presenting both as true.
- Use latest ProjectState as authority for the resolved/current conclusion.
- If latest ProjectState does not resolve a historical conflict, report it
  under Notes / uncertainty instead of choosing a side.
- Historical findings are not current confirmed findings unless latest
  ProjectState records them.
- Historical actions are not current planned next actions unless latest
  ProjectState.next_actions records them.
- Cite historical progress as selected run <timestamp>
  progress_since_last.md, never as a raw artifact.
- Disclose missing progress summaries, unparseable excluded run names, and
  truncated progress context.

Current-state grounding rules:
- Do not invent findings, decisions, failures, blockers, questions, or actions.
- Confirmed findings must come only from latest ProjectState confirmed_findings.
- Clearly label latest tentative_hypotheses as tentative and unverified.
- Failed attempts and blockers must come from latest ProjectState.failed_attempts.
- Open questions must come only from latest ProjectState.open_questions.
- Planned next actions must come only from latest ProjectState.next_actions.
- SOURCE snippets come only from latest combined_notes.md and are bounded.
  They support latest state but do not create state and are not direct raw reads.
- Attribute latest evidence as project_state.json, combined_notes.md SOURCE
  <source path>, or project_state.json evidence source <source path>.

Output requirements:
- Return Markdown only.
- Target approximately 500-1000 words using concise, shareable bullets.
- Do not add a conclusion or prose after Notes / uncertainty.
- Use exactly these headings, in this order:

# Project Group Update

## TL;DR
## Update window
## Progress this period
## Current status
## Confirmed findings
## Tentative hypotheses / interpretation
## Failed attempts / blockers
## Open questions
## Planned next actions
## Evidence pointers
## Notes / uncertainty

Progress window:
- Requested: checkpoint runs since {requested_since}
- Selected run count: {selected_run_count}
- Selected runs:
{selected_runs}
- Missing progress summaries:
{missing_progress_runs}
- Excluded unparseable run directories:
{unparseable_runs}
- Progress context truncated: {progress_window_truncated}
- Entries come only from selected runs' progress_since_last.md files.

Selected bounded progress entries:
{progress_window}

Latest ProjectState (sole current-state authority):
--- BEGIN latest project_state.json ---
{project_state}
--- END latest project_state.json ---

Latest supporting checkpoint summary:
--- BEGIN latest checkpoint_summary.md ---
{checkpoint_summary}
--- END latest checkpoint_summary.md ---

Latest SOURCE-marked evidence selected from combined_notes.md:
{source_snippets}

Latest source lookup diagnostics:
{source_diagnostics}

Latest optional checkpoint files unavailable or empty: {missing_optional_files}
"""
