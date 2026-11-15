# DOC-SYNC BRIEF (fill every {{...}} except the marker names `{{MAINTHREAD}}` etc., which stay literal; this file is the Agent prompt of phase A; phase B goes to the SAME agent by SendMessage)
# Agent(subagent_type: "adcm-toolkits:executor", model: "sonnet") (no plugin → `general-purpose` + `model: "sonnet"`). 1 of the 20, 0 Opus quota.

TASK: Doc-sync of Wave {{Wave}} · phase {{d | e}} in the brain `{{docs_dir}}` (its own git repo, push to main). Two phases.
  PHASE A (now): build the sheet + markers file and leave `docsync-apply --check` clean; write NO doc.
  PHASE B (when I SendMessage you the marker values and the answers to your doubts): apply, verify, commit, push.
  One-message variant (merge close, no marker to wait for): the values are below; run A and then B without stopping.
  Facts (verified by the orchestrator, use them literally): {{MR / PR id and state · pipeline · gate verdicts · merges · deploy}}.
  Target state: {{e.g. wave ⛔ pending merge | ✅ merged <date> | ✅ in prod <date>}} in the wave map, the §7 phase headers and the plan states;
  tasks {{IDs}} ✅ in detailed-plan with their Scope manifests set to what was touched; later-wave manifests and their §7
  prompts refreshed when this wave changed their surfaces; DoD-human rows {{to add (number = max+1, verify) | to strike ✅}};
  logbook entry `### <today> — Wave {{Wave}} …` with every §2b step 1 field, `**Agents used:**` then `- **Main thread:** {{MAINTHREAD}}`.
  Expected open DoD-human count after the write: {{n of m}}.
  Markers to leave unresolved in phase A: {{MAINTHREAD}} {{SKILLSYNC}} {{MAP}} {{SMOKE}} {{POSTPROD}} — keep only those listed: {{list}}.
FILES: work folder `{{scratch_dir}}` (sheet.json — paths relative to --root —, markers.json, logbook-entry.md, commit-msg.txt — nothing in the brain).
  Inputs: the wave's handoffs {{handoff paths}} · {{gate report paths | none}} · protocol: execute.md §2b only (read that section).
  Docs the sheet may touch: task.md · execute.md (§7 headers, regenerated later-wave prompts) · detailed-plan.md · master-plan.md
  execution-state block{{ · other docs}}. Print single lines or `grep -n` hits, never whole docs (lines can be 1,000 chars).
SKILLS: none.
DELIVERABLE: A — the sheet in the `docsync-apply` format (ops sub · tick · insert_before / insert_after · append_rows · logbook),
  one `why` per op, plus logbook-entry.md and commit-msg.txt (`docs({{wave}}): …`, blank line, `Refs: …`, the session trailers).
  B — the docs written by the sheet, `map/` refreshed, one commit pushed.
DOD-SLICE: A — `docsync-apply --sheet {{scratch_dir}}/sheet.json --markers {{scratch_dir}}/markers.json --root {{docs_dir}} --check` → `DOCSYNC: <n> ok · 0 failed · <k> open
  placeholders` (k = the markers above). B — `git -C {{docs_dir}} pull --ff-only` → {{map-refresh command with one `--human` per born
  entry | skip: no map}} (its `MAP:` line is the MAP marker) → fill markers.json → the same `--check` (0 failed, 0 open) → `--write` →
  `status-digest --brain {{docs_dir}}` → `DIGEST: ok` and the expected count → `plan-audit --brain {{docs_dir}} --check` (report
  its line, never seal) → `git add` by explicit path (the docs, `map/`,
  `handoffs/{{Wave}}-*`, qa files) → `git commit -F {{scratch_dir}}/commit-msg.txt` → `git push`.
STOP IF: an anchor no longer matches and the neighbouring line does not resolve it · `pull --ff-only` fails · the digest
  count differs from the expected one (report it BEFORE committing) · ~45 turns (partial RETURN).
FORBIDDEN: `plan-audit --seal` · `git add -A`, `commit -a`, `stash`, checkout, reset (other sessions share the tree) · editing a doc outside the sheet ·
  writing any doc in phase A · other repos · real names, internal figures or URLs in the docs · merging.
RETURN: A — `READY` or `BLOCKED` · the `DOCSYNC:` line · table file → n ops · numbered doubts · markers still needed.
  B — commit hash · the `DOCSYNC:` line of `--write` · the plan-audit result line · the `DIGEST:` line plus its WAVES / NEXT / PENDING-HUMAN lines. No URLs.
