# Policy

How `deps-check` decides what a run may touch. The human `## Policy` section lives in `dependencies.md` of the project's context skill; its
template is `templates/dependencies.md.tmpl` of the `code-project-context-generator` skill, the only copy: this page documents the section and
holds no second template. Examples use Acme.

## Precedence

1. Built-in never-auto names (cannot be overridden)
2. The Policy tables of `dependencies.md`
3. `renovate.json` `packageRules`
4. dependabot config: presence only (`review: dependabot config present — not parsed`), manual
5. Defaults

## The Policy section

The block between the auto-generated markers is rewritten by `deps-check context`; `## Policy` and everything below it is human-owned,
preserved and binding. `deps-check` finds the tables under `### Rules`, `### Verification` and `### Smoke` and the bullet list under
`### Delivery` (`- Key: value`). Header names are case-insensitive: keep the columns. `Package` accepts a glob (`@acme/*`). An unknown rule or a
malformed row gives `review: dependencies.md:<line> …` and the row is ignored.

### Rules

| Package | Rule | Value | Why | Since | Review by |
|---|---|---|---|---|---|
| node | never-auto | | npm binary package; shadows the runtime of every npm script | 2026-10-25 | |
| typescript | cap | `<6` | the Acme build loader has no TypeScript 6 support yet | 2026-10-25 | 2027-01-31 |
| react | hold-major | | the Acme design system targets 18 | 2026-10-25 | 2027-03-31 |
| acme-pdf | pin | | saved exact on purpose | 2026-10-25 | |
| @acme/* | group | acme-sdk | released together | 2026-10-25 | |
| lodash | hold | | waiting for an upstream audit fix | 2026-10-25 | 2026-12-01 |
| acme-tokens | min-age | 7 | the registry yanks releases quickly | 2026-10-25 | |

| Rule | Value | Effect |
|---|---|---|
| `never-auto` | none | never touched; always a human decision, listed under `Para ti` |
| `hold` | none | no bump at all |
| `hold-major` | none | patch and minor only |
| `cap` | highest allowed range, e.g. `<7` (required) | no bump beyond it |
| `pin` | none | keep the saved version exact |
| `group` | group name (required) | the members bump together |
| `min-age` | days (required) | a release must be at least that old; security fixes skip it |

`Review by` is a reminder, not an expiry: once the date passes on a `never-auto`, `hold`, `hold-major` or `cap` row, `review: … hold expired … —
still held` appears and the rule stays in force until the row is edited. A `cap`, `group` or `min-age` row without its Value is ignored with a
`review:` line.

### Verification

Overrides the detected command of the same Step. Where = `local`, `ci` or `both`.

| Step | Command | Where | Notes |
|---|---|---|---|
| lint | npm run lint:ci | both | |
| e2e | npx playwright test --reporter=json | local | needs port 3000 free |

### Smoke

Routes for the before and after screenshots; the mask lists the CSS selectors painted over in the shot (`--mask`).

| Route | Name | Mask (CSS selectors, comma-separated) |
|---|---|---|
| / | home | |
| /compare | compare | .live-clock, .rotating-banner |

### Delivery

- Server: `npm start`, port 3000, ready `http://localhost:3000/`, env `PORT=3000 HOST=127.0.0.1`
- Shot command: built-in (deps-smoke)
- Changelog: docs/dependencies/CHANGELOG.md
- Reviewer: `@reviewer-handle` (gitlab)
- Commit identity: `dev@example.com`
- Max majors per run: 3
- Priority majors: express
- Notes: the Acme site deploys from a Node 24 image

`none`, `n/a`, `-`, an empty value, a `_pending …` value or a leftover `{{...}}` counts as unset. The changelog defaults to
`docs/dependencies/CHANGELOG.md`; a root file is a Delivery override. The commit identity is what preflight compares with the effective
`user.email`.

### renovate.json mapping

| `renovate.json` | Becomes |
|---|---|
| `matchPackageNames`, `matchDepNames`, `matchPackagePrefixes`, `matchPackagePatterns` | the packages a rule selects |
| `allowedVersions` (a range or `/regex/`) | cap |
| `enabled: false` with `matchUpdateTypes: [major]` | hold-major |
| `enabled: false` without update types | hold |
| `minimumReleaseAge`, `stabilityDays` | min-age |
| `groupName` | group |
| top-level `minimumReleaseAge` | the default min-age |
| `vulnerabilityAlerts` without an age | security fixes skip min-age |
| `extends` | not expanded (a `review:` line) |

## Never-auto

`node`, `npm`, `pnpm`, `yarn`, `corepack`, `bun` and `deno`, as dependencies. A package of that name puts a binary in `node_modules/.bin/` and
shadows the runtime of every `npm run` script, so bumping it changes what runs the build and what ships in the bundle. The plan reports it
as `SHADOWED by node@<version>` and lists it under `Para ti`: the owner decides whether to remove it or keep it pinned exact, and that
decision comes before any runtime decision.

## Families

A family moves as one wave step. When a member is held, capped or lagging, the whole family stays pending (`family incomplete: …`).

| Family | Members |
|---|---|
| `next` | next, eslint-config-next, @next/* |
| `react` | react, react-dom, react-is, @types/react, @types/react-dom |
| `vitest` | vitest, @vitest/* |
| `playwright` | @playwright/test, playwright, playwright-core, and the CI image `mcr.microsoft.com/playwright:v<ver>-*` |
| `typescript-eslint` | typescript-eslint, @typescript-eslint/* |
| `eslint` | eslint, @eslint/js |
| `storybook` | storybook, @storybook/* |
| `sentry` | @sentry/* |
| `tailwind` | tailwindcss, @tailwindcss/* (3 to 4 is flagged as a migration) |
| `jest` | jest, ts-jest, babel-jest, @types/jest |
| `prisma` | prisma, @prisma/client |
| `angular` | @angular/* |
| `nestjs` | @nestjs/* |
| `sass` | sass, sass-embedded |
| `babel` | @babel/* |

`@types/<x>` couples to `<x>` by major; `@types/node` couples to the major of the runtime pin.

## Risk, waves and order

- Risk: `@types` 1 · other dev dependency 2 · other prod dependency 3 · framework 4 · runtime, `packageManager` or base image 5. One more when at
  least 20 tracked files import the package (`git grep -l` of `from '<name>` or `require('<name>`); the cap is 5 and a family takes its maximum.
- Framework set: express, fastify, koa, @nestjs/core, next, react, react-dom, vue, nuxt, @angular/core, svelte, astro, tailwindcss,
  typescript, webpack, vite, eslint, jest, vitest, @playwright/test, prisma, @prisma/client, drizzle-orm, sequelize, typeorm,
  @supabase/supabase-js.
- One patch+minor wave per run. Majors take ONE step per family per run (the target is the latest of major+1 when the latest skips a major).
- Order of majors: the ones that close advisories first (by severity), then `--prioritize` or the Delivery `Priority majors`, then ascending
  risk, then name. The cap is 3 per run (`--max-majors`, Delivery `Max majors per run`); the rest is pending.
- Release age: a release younger than 3 days waits (`min-age`, `minimumReleaseAge`); security fixes skip it.
- Transitive advisory: a non-major `fixAvailable` through a direct parent goes in patch+minor; else an override in the same major goes in
  patch+minor; else a `Para ti` line. An override is added or raised, never removed automatically.
- Peer dependencies are never bumped.

## Runtime and CI alignment

- Node pin: `.nvmrc`, then `.node-version`, `engines.node` (the highest installed version that satisfies it), `devEngines`. The LTS status
  comes from the Node release schedule; without network the embedded table (dated in the digest) is used.
- Runtime majors (Node, `.nvmrc`, `engines`, the CI image) are a wave only when the deploy runtime is declared in the repo: a Dockerfile, a CI
  deploy image, `engines` with engine-strict, or platform config. Otherwise a `Para ti` line asks the owner which line to deploy.
- CI images: a node image or Dockerfile major that differs from the pin becomes an `align` edit in the patch+minor wave (it moves the image to
  the pin, never the pin); the Playwright image follows the locked `@playwright/test` in the same wave; the `supabase` CLI pin in CI follows
  the `supabase` devDependency; pip `==` pins in CI move by patch or minor through PyPI. Full-version image tags, services, actions and
  base-image majors are manual: `Para ti`.
- Install scripts: a new package with a build or install script (`allowBuilds` in a pnpm workspace) is a STOP and a `Para ti` line.
