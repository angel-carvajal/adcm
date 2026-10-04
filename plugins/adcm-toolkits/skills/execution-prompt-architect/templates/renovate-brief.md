# RENOVATE BRIEF (fill every {{...}}; this file is the Agent prompt; ONE brief per needed block)
# Agent(subagent_type: "adcm-toolkits:executor") (no such type in this session → `Agent(subagent_type: "general-purpose", model: "sonnet")` with the same brief). Order: ARTIFACTS → EXECUTE → TASK, root brain first, modules after; CONTEXT last. 1 of the 20, 0 Opus quota.

BLOCK: {{ARTIFACTS | EXECUTE | TASK | CONTEXT}}   Module: {{modules/<m> | none}}

TASK: Bring the block above of {{docs_dir}} to the checker's target protocol (`renovate_check.py --version`).
  renovate_check.py reported: {{output of renovate_check.py --brain <docs_dir> [--module <m>]}}
  INVARIANTS snapshot (must stay identical): {{INVARIANTS line of --invariants}}

FILES (only those of the block):
  EXECUTE   {{docs_dir}}/execute.md: surgical Edit only; §7 only PENDING waves (not ✅/🔀: ☐ 🔄 ⛔ ⏸).
  TASK      {{docs_dir}}/task.md (the module's own when set).
  ARTIFACTS {{docs_dir}}/artifacts.json, only through `courier_preflight.py --set-regen`.
  CONTEXT   only the `auto` files of the project's context skill; cpcg STEP 4.5 `--update`.

SKILLS: `adcm-toolkits:execution-prompt-architect` (CONTEXT also `code-project-context-generator`).

DELIVERABLE: the current text of {{skill_dir}}/templates/execute.md.tmpl, in the file's language;
  protocol markers stay verbatim even in a Spanish brain: `LAST LOG`, `> **Protocol:**`,
  `adcm-toolkits:*`, `- SKILLS:`.
  EXECUTE: §1.7 roles with the `adcm-toolkits:*` types and the per-call `model` rule · §2 the
  `status_digest.py --brain` line · §2b `**Next:**` / `**blocked**` · §4 resume via the digest ·
  §7 one `- SKILLS:` line per pending wave · the line `> **Protocol:** adcm-toolkits <target>`
  (write it, or update it in place).
  TASK: the canonical `## DoD-human pending` table, only when the check says `missing`; open
  rows of a legacy section are migrated into it, the legacy section is not deleted.
  ARTIFACTS: one `--set-regen` per row, with the command the check suggested; a `blocked:` suggestion → STOP (never store it); no publish.
  CONTEXT: the delta refresh of the `auto` files, nothing else.

DOD-SLICE: re-run `python3 {{skill_dir}}/templates/renovate_check.py --brain {{docs_dir}} [--module <m>] --invariants`
  → the block is `ok`; the INVARIANTS line is identical to the snapshot (`lines=` may grow).

STOP IF: an invariant would change; the block requires re-planning; the needed template text
  or skill cannot be found (report `blocked:`).

FORBIDDEN: re-planning; changing a wave's scope or state; touching closed waves or logbook
  history; publishing or calling the Artifact tool; git of any kind; other blocks' files.

RETURN: block · a diff summary per file (lines added/changed) · the real output of the
  re-run check and of `--invariants` · open questions. Short; never whole files.
