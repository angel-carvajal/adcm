TASK: Planning-time contradiction audit of the plan family of {{project_name}} AFTER the §7 phase prompts are written and BEFORE they are rendered or run (skill step 6b). Find places where two documents (or two sections) require incompatible things. Read-only: you decide nothing, you report.
FILES: {{docs_dir}}/{detailed-plan.md, execute.md (§1 · §5 · §6 gate sections · §7 prompts), task.md (wave map, DoD-human), master-plan.md, timeframe-plan.md}; the code only to confirm a disputed fact. Write nothing.
SKILLS: {{auditor_skills}} (none required).
DELIVERABLE: Cross-checks (run all, per wave and across waves):
Sources compared: gate items (§6) vs test and suite cards vs the §7 phase prompts (a-e) vs the owner's decisions (task.md DoD-human, memory).
1. Gate item that refuses (block / deny / reject / omit) vs a card, SCOPE or test-suite step that destroys the same noun (delete / purge / cascade / "drops to 0"): list every pair.
2. Every "N tables or rows at 0 after delete" count: enumerate the tables; none may be both a satellite to empty and the trigger of a blocking reason.
3. FK / cascade census in cards: tag each FK (cascade · explicit purge · null · block); gate items and suite cards must quote the same disposition.
4. Two reasons that can apply at once: a stated precedence, and one fixture per reason that cannot trigger another.
5. Any destructive-semantics choice not yet decided: it must be a DoD-human row in task.md now, never found at the gate.
6. Mutation control per blocking rule: a test that goes red when the rule is removed; a contradiction makes one of the two tests impossible to write.
7. Phase prompts of one wave (§7 a-e) vs the gate checklist (§6), the cards and the owner's decisions must agree on scope, names, counts and order of checks.
8. Cross-wave: a later wave's assumption vs what an earlier wave actually delivers; dependencies in the wave map vs the cards.
Scoped mode: when the orchestrator passes a list of waves (the stale_waves of `plan-audit --check --json`), audit only those waves' blocks against the rest of the plan; line 1 of the RETURN keeps its grammar.
DOD-SLICE: every cross-check has a verdict (CONTRADICTION / CLEAR / N-A) with the lines examined; every contradiction has both sides quoted with file:line.
STOP IF: a file named above is missing or unreadable (RETURN `blocked: <file>`).
FORBIDDEN: editing any file; choosing between the two sides; softening or merging contradictions; dropping a finding because it looks minor. NEVER resolve a contradiction silently, in the report or in a card.
RETURN: line 1, exactly (the gate reads only this line):
PLAN-AUDIT: PASS|FAIL · contradictions <n> · open <n>
PASS only with 0 contradictions and open 0; open = questions still waiting for the owner. Then one table, one row per finding:
| id | side A (file:line, quote) | side B (file:line, quote) | severity (blocker · major · minor) | question for the owner | resolution (empty until the owner answers) |
After the table: the 8 verdicts, one line each. The main session saves this RETURN verbatim to {{docs_dir}}/qa/plan-audit.md, takes the questions to the owner, has the cards and phase prompts fixed, re-runs this audit, and only then runs `plan-audit --brain {{docs_dir}} --seal`.
