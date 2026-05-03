# OpenRTC v0.1.0 release checklist

This page exists so the v0.1.0 release can be cut without re-reading the
design doc, the changelog, and the publish workflow in three different
tabs. The full design and acceptance picture lives in
`docs/design/v0.1.md` (locked); this file is the operator runbook.

## Pre-flight (before tagging)

Verify each of these on the merge target (typically `main`):

- [ ] Branch with the v0.1 work is merged to `main` (e.g. open and merge
      a PR from `feat/light-websocket`). Per AGENTS.md and PROMPT.md, do
      not push directly to main.
- [ ] `make test` passes locally on the latest commit of `main`. The
      CI test workflow runs the full matrix (3.11 / 3.12 / 3.13);
      check it's green for the merge commit too.
- [ ] `make lint` and `make typecheck` are green on the merge commit
      (covered by the CI lint workflow).
- [ ] The CI density gate (`.github/workflows/bench.yml`) is green on
      the merge commit. The job runs
      `tests/benchmarks/density.py --sessions 50 --rss-budget-mb 4096`
      and uploads `density-result-${run_id}` as an artifact you can
      attach to the release notes if you like.
- [ ] `docs/changelog.md` has a `[Unreleased]` block with the v0.1.0
      content already staged. If you've added more PRs to `main` since
      that block was written, update it.
- [ ] (Optional) Run the integration suite against a local LiveKit dev
      server with real provider credentials:
      ```bash
      docker compose -f docker-compose.test.yml up -d
      OPENAI_API_KEY=sk-... uv run pytest -m integration -v
      docker compose -f docker-compose.test.yml down
      ```
      The §8.4 acceptance criterion is structurally proven by the
      coroutine harness; this run validates against a real STT/LLM/TTS
      stack one more time before tagging.

## Tagging

```bash
git checkout main
git pull --ff-only
git tag -a v0.1.0 -m "OpenRTC 0.1.0 — coroutine-mode worker"
git push origin v0.1.0
```

`hatch-vcs` derives the wheel version from the tag, so the resulting
build is exactly `0.1.0`. (Verify with `git describe --tags --abbrev=0`
before pushing.)

## Creating the GitHub release

1. Open `https://github.com/mahimailabs/openrtc/releases/new`.
2. Pick the new `v0.1.0` tag.
3. Title: `v0.1.0 — coroutine-mode worker`.
4. Body: copy the entire `### v0.1.0 — coroutine-mode worker (default
   behavior change)` subsection from the `[Unreleased]` block in
   `docs/changelog.md`. Tweak the prose if anything feels too internal
   for a public release note. The migration block is the most
   operator-facing piece — keep it.
5. Click **Publish release**.

## What fires automatically when you publish

- `.github/workflows/publish.yml` triggers on the release event, builds
  the wheel via `uv build`, publishes to PyPI using
  `secrets.PYPI_API_TOKEN`, then commits a versioned section to
  `docs/changelog.md` (under the `<!-- releases -->` marker) using
  `secrets.CHANGELOG_PUSH_TOKEN`. The marker is preserved.
- `.github/workflows/deploy-docs.yml` runs (because the publish workflow
  pushes a commit). The VitePress site re-deploys with the v0.1.0
  changelog section visible.

## Post-release verification

- [ ] `pip install openrtc==0.1.0` succeeds in a clean venv.
- [ ] `python -c "import openrtc; print(openrtc.__version__)"` prints
      exactly `0.1.0`.
- [ ] `pip install 'openrtc[cli]'` then `openrtc --help` works and
      shows the `--isolation` and `--max-concurrent-sessions` flags
      under the **OpenRTC** panel of `openrtc dev --help`.
- [ ] The release shows up at
      `https://pypi.org/project/openrtc/0.1.0/`.
- [ ] `docs/changelog.md` has a real `## [0.1.0] - YYYY-MM-DD` entry
      under `<!-- releases -->` (added by the publish workflow).
- [ ] The docs site at `https://openrtc.mahimailabs.com/` (or wherever
      VitePress deploys) shows the new release in its changelog page.

## After release: bump the dev fallback

Once `v0.1.0` is tagged, `hatch-vcs` will start producing
`0.1.0.devN+...` versions on `main`. The fallback for environments
without a reachable tag is set in two places — keep them in sync:

- `pyproject.toml`: `[tool.hatch.version.raw-options].fallback_version`
- `src/openrtc/__init__.py`: the `PackageNotFoundError` branch

Bump both to `0.2.0.dev0` (or whatever the next planned target is) in
the first PR after the release.

## If something goes wrong

- **PyPI publish failed but the tag is up.** Re-run the
  `Publish OpenRTC` workflow from the Actions tab (it accepts
  `workflow_dispatch`). The job is idempotent on PyPI: PyPI rejects
  duplicate version uploads, so a retry that already has the wheel up
  will fail loudly and is safe.
- **You tagged the wrong commit.** If the tag has not been pushed,
  `git tag -d v0.1.0`. If it has, deleting the remote tag will
  invalidate any cached PyPI link — coordinate with the team before
  retagging. Prefer cutting `v0.1.1` instead.
- **Changelog auto-prepend failed.** Check whether
  `secrets.CHANGELOG_PUSH_TOKEN` is set; if it isn't, the workflow
  falls back to `GITHUB_TOKEN` and the docs deploy step won't fire.
  Add the section manually and re-run the docs workflow.
