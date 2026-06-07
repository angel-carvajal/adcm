# Context Hooks

Hooks live in this folder as `.md` files. Each one summarizes a domain (business, project, person) that can be injected into the Council's advisors when the user invokes with `--context <name>`.

## Invocation syntax

```
ask the council --context example: <question>
ask the council --context mycompany: <question>
ask the council --context mycompany,otherproject: <question>
```

The hook name corresponds to the file name without the `.md` extension. `--context example` reads `contexts/example.md`. You add your own hooks by creating `.md` files in this folder.

## Rules for writing a hook

1. **Maximum 500 words.** If it's longer, it belongs in a business-init skill, not in a Council hook. Hooks are the tactical distillate, not the encyclopedia.

2. **Recommended structure:**

   ```markdown
   # Context: <Name>
   
   ## What it is
   1-3 sentences. Identity of the business/project/domain.
   
   ## Model / How it operates
   3-6 sentences. How it makes money, what it does, for whom.
   
   ## Current state
   2-4 sentences. Business phase, what works, what's broken.
   
   ## Real constraints
   Short list. What CANNOT be done (financial, legal, capacity).
   
   ## Risk appetite
   1-2 sentences. How much the owner is willing to bet on this decision.
   
   ## What NOT to mention externally
   Short list. Confidential info the user protects.
   ```

3. **No flourish.** This is not marketing. It's an information feed so the advisors have real context.

4. **Honesty over aspiration.** If the business is struggling, say so. If it's growing, say so. Advisors advise better with reality, not with the LinkedIn version.

## Included hooks

- `example.md` — a sanitized sample hook (fictional company "Acme Widgets Co."). It serves only to show the format. Copy it, adapt it to your real domain, or delete it. Do not put real confidential information in a public repo.

## Privacy

Hooks can contain sensitive information about your business. If you're going to publish or share your copy of this skill, **do not include your real hooks in `contexts/`** — keep them local or in a private repo. The public framework only ships `example.md`.

## Reminder about the Outsider

The Outsider **never** receives these hooks, even if the user enables them. That is by design — its value is being context-blind. Don't try to "help it" by passing it the hook.
