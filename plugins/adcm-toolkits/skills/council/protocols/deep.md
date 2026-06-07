# Protocol: Deep (Stage 2 — Cross-review)

**Current status: STUB.** This version of the Council does not run a real cross-review. The `--deep` flag only adds a note to the Chairman's output explaining that Stage 2 is pending implementation.

This file documents the **target design** for when it is implemented, not the current behavior.

---

## Target design (to be implemented)

### When it activates
When the user invokes the Council with the `--deep` flag. Example:

```
ask the council --deep: should I hire a second person for my team?
ask the council --deep --context example: should I hire a second person for my team?
```

### How it will work

After Stage 1 (the 5 advisors have already responded), before the Chairman:

1. **Anonymize the 5 responses.** Each advisor receives the responses of the other 4 labeled as "Advisor A / B / C / D" — without knowing which one is the Strategist, the Adversary, etc. (This is what Karpathy does in LLM Council to kill sycophancy: if you don't know who said what, you can't agree out of deference).

2. **Each advisor answers 3 questions:**
   - **Strongest insight I missed:** Which of the 4 responses brings something my own reasoning did not include and that changes my stance?
   - **Weakest insight:** Which of the 4 responses has a logical crack or a weak assumption I can dismantle with evidence?
   - **Refinement of my own response:** In light of what I read, what do I correct, reinforce, or abandon from my original response?

3. **The Chairman now receives 5 original responses + 5 reviews + 5 refined responses.** Its synthesis mainly uses the refined ones, but it can cite the originals if there was a significant change (because the change itself is information).

### Cost

- Roughly 2x the tokens and 2x the time of Stage 1.
- Only justified for decisions with a high cost of error or high ambiguity.

### Chairman output in deep mode

The Chairman adds a short section at the end:

```
**Changes after cross-review:** [1-2 sentences. What changed in the verdict from running Stage 2. If the verdict did not change, say so — it's valuable information that the first instinct was correct.]
```

---

## Why it is a stub for now

Implementing context-isolated cross-review in claude.ai requires coordinating sequential reads with clean anonymization, which adds operational complexity that adds no value until the Council has proven its usefulness in Stage 1. It will be implemented once the standard flow is confirmed to work well in production.
