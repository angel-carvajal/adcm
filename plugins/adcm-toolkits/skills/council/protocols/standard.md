# Protocol: Standard

The Council's default flow. Requires no flags. It is the fastest mode and sufficient for 90% of decisions.

## Steps

1. Parse the user's question and flags (`--context` if present).
2. Load context hooks if applicable.
3. Convene the 5 advisors in parallel (Claude Code) or sequentially with context isolation (claude.ai / Cowork).
4. The Outsider NEVER receives injected context, even if `--context` is present. The other 4 do.
5. Convene the Chairman with the 5 responses + the original question.
6. Present to the user: Chairman's verdict first, individual responses after.

## What Standard does NOT do

- No Stage 2 (cross-review).
- No second rounds.
- No "forced consensus". If the Chairman has to take a stance without consensus, it does.

## When to use

- Day-to-day tactical decisions.
- Questions with a low cost of error.
- When there are time or token limits.
- When the user did not specify `--deep`.
