# RENOVATE BRIEF (fill every {{...}}; this file is the Agent prompt; ONE brief per needed block)
# Agent(subagent_type: "adcm-toolkits:executor") (no such type in this session → `Agent(subagent_type: "general-purpose", model: "sonnet")` with the same brief). Order: ARTIFACTS → EXECUTE → TASK → RULES, root brain first, modules after; CONTEXT last. 1 of the 20, 0 Opus quota.

BLOCK: {{ARTIFACTS | EXECUTE | TASK | RULES | CONTEXT}}   Module: {{modules/<m> | none}}

TASK: Bring the block above of {{docs_dir}} to the checker's target protocol (`renovate_check.py --version`).
  renovate_check.py reported: {{output of renovate_check.py --brain <docs_dir> [--module <m>]}}
  INVARIANTS snapshot (must stay identical): {{INVARIANTS line of --invariants}}

FILES (only those of the block):
  EXECUTE   {{docs_dir}}/execute.md: surgical Edit only; §7 only PENDING waves (not ✅/🔀: ☐ 🔄 ⛔ ⏸).
  TASK      {{docs_dir}}/task.md (the module's own when set).
  ARTIFACTS {{docs_dir}}/artifacts.json, only through `courier_preflight.py --set-regen`.
  RULES     the files in `--json` `blocks.rules.findings` (memory files = `<memory dir>/<file>`, or relative to `<config>/projects/` when several dirs; the text shows at most 6).
  CONTEXT   only the `auto` files of the project's context skill; cpcg STEP 4.5 `--update`.
SKILLS: `adcm-toolkits:execution-prompt-architect` (CONTEXT also `code-project-context-generator`).

DELIVERABLE: the current text of {{skill_dir}}/templates/execute.md.tmpl, in the file's language; markers stay
  verbatim even in a Spanish brain: `LAST LOG`, `> **Protocol:**`, `adcm-toolkits:*`, `- SKILLS:`.
  EXECUTE: §1.7 roles with the `adcm-toolkits:*` types and the per-call `model` rule · §2 the `status_digest.py
  --brain` line · §2b `**Next:**` / `**blocked**` · §4 resume via the digest · §7 one `- SKILLS:` line per pending
  wave · the line `> **Protocol:** adcm-toolkits <target>` (write it, or update it in place).
  TASK: the canonical `## DoD-human pending` table, only when the check says `missing`; open rows of a legacy
  section are migrated into it, the legacy section is not deleted.
  ARTIFACTS: one `--set-regen` per row, with the command the check suggested; `blocked:` → STOP; no publish.
  RULES: `fix` findings only. Memory files: APPEND at the end `**Superseded (protocol <target>, <YYYY-MM-DD>):**
  <correction> (line N: "<snippet>")`, never edit or delete an existing line; a MEMORY.md finding gets only ` · ⚠ superseded
  (protocol <target>)` appended to that hook line (no note). CLAUDE.md/AGENTS.md/README.md: edit the stale line in place.
  CONTEXT: the delta refresh of the `auto` files, nothing else.

DOD-SLICE: re-run `python3 {{skill_dir}}/templates/renovate_check.py --brain {{docs_dir}} [--module <m>] --invariants`
  → the block is `ok` (RULES: `RULES ok`, `review` findings may remain); INVARIANTS identical (`lines=` may grow).

STOP IF: an invariant would change; the block requires re-planning; the template text or skill is not found (`blocked:`).

FORBIDDEN: re-planning; changing wave scope or state; touching closed waves or logbook history; publishing; the
  Artifact tool; git; other blocks' files; files not in the findings; any config-dir file outside the listed memory dir, in particular `~/.claude*/CLAUDE.md` and `~/.claude*/ORCHESTRATOR.md`.

RETURN: block · a diff summary per file (lines added/changed) · the real output of the re-run check and of
  `--invariants` · open questions · RULES: the `review` findings verbatim. Short; never whole files.
