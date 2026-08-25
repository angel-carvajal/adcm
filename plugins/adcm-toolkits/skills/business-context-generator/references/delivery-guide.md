# Delivery Guide

How to hand the generated `business-init-[business-slug]/` skill to the user. Read on-demand
at STEP 5. Offer both options and let the user choose; A is the better long-term
home when the user maintains a private plugin marketplace.

## Option A — The user's private plugin marketplace (recommended)

Many users keep per-business Claude Code plugin marketplaces (private git repos with
a `.claude-plugin/marketplace.json` and `plugins/<plugin>/skills/`). If this user
does:

1. **Resolve the location by convention first, ask only as fallback.** The standard
   container layout (see
   `../../execution-prompt-architect/references/project-structure.md`) puts each
   business's marketplaces under `<container>/ai/` — business context belongs in
   `<container>/ai/<slug>-{ai|ia}-admin/plugins/<slug>-admin/skills/`. If that
   marketplace exists, that's the home; if the container exists but the marketplace
   doesn't, offer to scaffold it there (own git repo — the container itself is never
   a git repo). Only when no container/convention is visible, ask the user to point
   you at the target plugin directory — e.g.
   `<marketplace-repo>/plugins/<plugin-name>/skills/`. If the business already has
   sibling skills (quote generators, councils, etc.), the same plugin is usually
   the right home.
2. **Place the folder.** Copy `business-init-[business-slug]/` (SKILL.md + `references/`)
   into that `skills/` directory. Verify the frontmatter `name` equals the folder
   name — most marketplace validators require it.
3. **Walk the user through the release** (do it with them, but never push):
   - Bump `version` in the plugin's `.claude-plugin/plugin.json` (adding a skill
     is typically a minor bump).
   - If the plugin/marketplace descriptions enumerate skills, update them; if the
     repo has README/manifest generation tooling, re-run it.
   - Commit with their convention, e.g.
     `feat(business-init-acme-coffee): add business context skill + bump 0.2.0`.
   - **Pushing the private repo is the user's call — never push it yourself.**
4. Remind them: teammates get the skill via their marketplace's normal
   install/update flow.

Example: for a fictional "Acme Coffee Roasters" with container `~/acme-coffee/`, the
folder `business-init-acme-coffee/` would land in
`~/acme-coffee/ai/acme-coffee-ai-admin/plugins/acme-admin/skills/business-init-acme-coffee/`
(marketplace repo `acme-coffee-ai-admin`, its own git, inside the non-git container).

## Option B — Standalone `.skill` zip

For users without a marketplace, or to install on claude.ai:

1. Save the folder under the session's output directory
   (`<output-dir>/business-init-[business-slug]/`).
2. Zip it with the `.skill` extension:

   ```bash
   OUT_DIR="<output-dir>"
   SLUG="business-init-[business-slug]"
   [ -d "$OUT_DIR/$SLUG" ] || { echo "Error: $OUT_DIR/$SLUG does not exist."; exit 1; }
   ( cd "$OUT_DIR" && zip -r "$SLUG.skill" "$SLUG/" )
   ```

3. Deliver the `.skill` file through the mechanism available in the environment
   (download link, file output, etc.), or tell the user they can copy the raw
   folder into their personal skills directory (e.g. `~/.claude/skills/`).
4. If zipping isn't possible in the environment, deliver the folder as-is and say
   so — never fail the delivery because packaging failed.

## Final checklist (both options)

- [ ] Everything the owner marked confidential is in `INTERNAL.md` — and none of
      it leaked into the public-safe files.
- [ ] The hard rules the owner stated are in the generated SKILL.md.
- [ ] Frontmatter `name` == folder name, kebab-case, and the description carries
      the generous triggers (brand, entity, domain, nicknames, disambiguation).
- [ ] `[TO BE DEFINED]` items are listed under "Pending context" in
      `objectives.md`.
- [ ] The user knows the skill is a living document: re-running this generator on
      it (update mode) refreshes it without losing anything.
