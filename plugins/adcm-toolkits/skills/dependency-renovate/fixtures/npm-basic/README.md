# npm-basic

Generic Acme fixture for deps-check-selftest; not a real project.

A tiny npm site with a package-lock v3 that exercises the planner of the dependency-renovate skill:

- `.nvmrc` 20.11.0, a past-EOL runtime on 2026-10-25, and the `node` npm package, which shadows it;
- a `.gitlab-ci.yml` with merge-request pipelines, a `guard` job on `node:20`, an `audit` job allowed to
  fail and an `e2e` job on a Playwright image older than the locked `@playwright/test`;
- a `Dockerfile` whose two stages build `FROM node:${NODE_VERSION}-alpine`;
- a `renovate.json` with a typescript cap, disabled react majors, a playwright group and a 3-day minimum
  release age.

`stubs/` holds what the selftest fakes replay: `npm outdated`, `npm view <name> time`, `npm view
<name>@<version> repository.url homepage`, an `npm audit` report (used only to exercise the JSON
subprocess helper), the bulk advisory answer, registry manifests, and the Node schedule and dist index.
No `.npmrc` here: the secret-leak case writes its own.
