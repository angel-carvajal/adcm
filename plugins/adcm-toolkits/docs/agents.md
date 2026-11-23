# adcm-toolkits role agents

_Moved from `agents/README.md` in 0.20.0: every `.md` inside `agents/` loads as an agent._

Six sub-agent types that fix the default model and the tool set of a delegation, so the brief no longer has to. Address them as `adcm-toolkits:<name>`, for example `Agent(subagent_type: "adcm-toolkits:auditor")`. The prompt you pass is the brief (TASK · FILES · SKILLS · DELIVERABLE · DOD-SLICE · STOP IF · FORBIDDEN · RETURN).

| name | model | tools | preload | use when |
|---|---|---|---|---|
| `courier` | sonnet | all except Edit, Write, NotebookEdit, Agent | `artifact-courier` | delivery close: republish, seal registry, links block |
| `auditor` | opus | Read, Grep, Glob, Bash | none | regression review or gate check; verdict ship or fix-first, full report under `REPORT:` when the brief names a path; never edits |
| `executor` | sonnet | all | none | implement one scoped brief and prove its DoD |
| `executor-frontend` | sonnet | all | `frontend-design` | `executor-frontend` on UI and frontend-code waves — when the wave loads design skills OR the task's FILES are frontend app code (components, pages, hooks/composables, client services/stores); cost: the `frontend-design` preload (~3.1k tokens); uses the `.design/` pack when present |
| `researcher` | sonnet | all except Edit, Write, NotebookEdit | none | sourced investigation or browsing; pass `model: opus` per call for a deeper pass |
| `digester` | sonnet | Read, Grep, Glob, Bash | none | status digest when the status script cannot parse the brain |

## Hooks and media

The plugin's `main-thread-guard` hook applies to the main session only; sub-agents (every agent in the table above) are exempt, except that none may write into the guard's state folder.

Sub-agents that capture screenshots return `MEDIA: sent ...` or `MEDIA: unsent: <paths>`; the main session sends unsent paths with SendUserFile by path without opening them, because judging images is a sub-agent job and the guard denies image reads on the main thread.

## Two protocol rules

Claude never merges an MR/PR and never pushes code to the default branch (the Reviewer merges; docs repos and marketplaces push to main directly), and only the courier returns links, exactly once per delivery close, in its RETURN.

## Reuse block

**Evidence duty (0.24.0).** When the brief has `EVIDENCE: spec`, `executor-frontend` writes `qa/evidence/<Wx>.json` (the `mr-evidence` spec) and returns an `EVIDENCE-SPEC:` line with its path; it never captures, never uploads and never touches the MR: the orchestrator asks what to send, and the `mr-evidence` launcher runs after the wave's verification.

The shared `## Reuse` section is a deliberate duplicate: identical in `executor` and `executor-frontend`, because an agent body has no include mechanism. Edit both copies together; a prefix check of the two `## Reuse` sections catches drift. The frontend sub-block lives only in `executor-frontend`. Both agents add the `REUSED` line and the `RULE-OF-TWO` line to their RETURN.

## Fallback

In a session without this plugin, call `Agent(subagent_type: "general-purpose", model: "<tier>")` with the same brief. The tier is the model column above.

## Preload cost

`skills:` preloading is eager: the full skill text enters the context of every spawn of that agent, used or not. Measured sizes: `artifact-courier` SKILL.md 4,666 B; `frontend-design` SKILL.md 9,390 B (about 3.1k tokens); `impeccable` SKILL.md 12,883 B (a user-level skill, not shipped here). Body sizes: `executor` 4,233 B, `executor-frontend` 5,900 B (15,290 B with `frontend-design`). Preloading both design skills would cost 22,273 B, about 7.4k tokens, over the 6k cap; with `frontend-design` alone it is about 3.1k tokens (9,390 B). So `executor-frontend` preloads only `frontend-design`; `impeccable` and any other design skill are loaded by the brief's `SKILLS:` line with `Skill`. Only courier and `executor-frontend` preload. If preloading does not resolve a name, `executor-frontend` loads `frontend-design` itself as its first step.

## Loading

Plugin agents are read at session start. After installing or updating the plugin, start a new session or run `/reload-plugins`. The `permissionMode`, `hooks` and `mcpServers` fields are ignored for plugin agents, so none is set.
