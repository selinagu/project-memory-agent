# Live-demo storyboards and narration

## 30–45 second silent README preview

Goal: make the value legible without audio. Use large terminal text and short
overlay captions.

| Time | Terminal action | Overlay |
| --- | --- | --- |
| 0–4s | Show the fixture files and `PROJECT_STATUS.md`. | “Back after two weeks. What changed?” |
| 4–12s | Type `pma checkpoint --project-dir .`; pause on the summary. | “Reconstruct current state” |
| 12–18s | Type `pma brief --project-dir .`. | “Recover goal, decision, blocker, next action” |
| 18–30s | Type the source-backed `pma ask` command; highlight decision/rationale and measurement evidence. | “Answers stay inside an evidence boundary” |
| 30–36s | Copy the update and show `git diff`. | “The repository moves on” |
| 36–45s | Type `pma freshness --project-dir .`; pause on `stale`. | “PMA knows when its memory expires” |

End card: “Project Memory Agent — reliable context recovery for long-running
software projects.” Do not speed up the output so much that source names become
unreadable.

## 2–3 minute narrated demo

### 0:00–0:20 — establish the problem

“This is Atlas Cache Gateway, a synthetic repository that represents a project I
haven't touched in two weeks. The files contain benchmark results, a failure
analysis, and a status note. Instead of rereading everything or trusting chat
history, I'll ask PMA to reconstruct a durable project state.”

Show `ls`, then the first screen of `PROJECT_STATUS.md`.

### 0:20–0:50 — reconstruct state

Type `pma checkpoint --project-dir .`.

“Checkpoint scans bounded repository evidence and writes both a current snapshot
and append-only history. The key point isn't just summarization: the resulting
state should preserve the goal, the chosen bounded key-prefix policy, the
high-churn validation blocker, and the next action.”

### 0:50–1:10 — fast re-entry

Type `pma brief --project-dir .`, then `pma memo --type self --project-dir .`.

“Brief is deterministic health and re-entry context. Memo turns the checkpoint
into a concise personal handoff. It must not invent a completed rollout or claim
that production traffic was validated.”

### 1:10–1:45 — recover a decision with evidence

Type the `pma ask --sources` command from `commands.txt`.

“I'm asking why we rejected full-cache refresh. PMA should explain that bounded
invalidation avoids unnecessary work, ground the tradeoff in the 91.2 millisecond
full-refresh result and increased origin load, and cite only the status,
benchmark, and failure-analysis files. This is bounded retrieval, not an open-ended
whole-repository answer.”

Pause so at least two distinct allowed sources can be read. Together they must
cover decision/rationale and measurement evidence; all three possible source
pairs satisfy this when the claims are supported. Prefer a clean take that
displays all three sources, but do not describe a fully supported two-source
answer as a hallucination merely because it omits redundant evidence.

### 1:45–2:15 — prove memory can become stale

Copy `/tmp/pma-live-demo-update.md` over `PROJECT_STATUS.md`, show the Git diff,
then type `pma freshness --project-dir .`.

“Now the repository says coverage dropped below the guardrail and rollout is
blocked. PMA compares current evidence with the saved checkpoint and marks that
memory stale rather than confidently serving yesterday's state.”

### 2:15–2:35 — close the loop

Type `pma brief --project-dir .`.

“The final brief recommends checkpointing again. That closes the lifecycle:
reconstruct, retrieve with sources, detect drift, and refresh. The demo fixtures,
gold expectations, privacy checks, and offline validation are all versioned with
the project.”

End on the architecture diagram or repository README.

## Presenter checklist

- Prepare a fresh workspace and validate the fixture before recording.
- Run at least three guarded rehearsals and manually inspect claims and sources.
  Acceptance requires two distinct allowed sources covering decision/rationale
  and measurement roles, the key measurements, and no forbidden completion
  claim. Prefer all three sources in the final recording. Use offline recheck
  when the deterministic contract changes; do not spend API calls to reevaluate
  already saved answers.
- Use a terminal profile with no host, username, API key, or shell-history leaks.
- Keep `commands.txt` nearby, but type each product command visibly.
- Verify the initial Git tree is clean and the update changes only
  `PROJECT_STATUS.md`.
- Verify no forbidden claim appears and freshness changes to stale.
- Record the narrated version first; derive the short cut from a verified take.
- Run the repository privacy scan on any transcript or media metadata before
  publishing.
