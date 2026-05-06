# Integration test harness

Tests under this directory talk to a real LiveKit server. They are gated by
`@pytest.mark.integration` and the `livekit_dev_server` fixture, which skips
cleanly when no server is reachable so `pytest -m integration` is safe in
environments that do not run the harness.

## Quick start

The compose file lives at the repository root (it is referenced from
`CONTRIBUTING.md` and the docs):

```bash
# Bring the dev server up.
docker compose -f docker-compose.test.yml up -d

# Run the integration suite.
uv run pytest -m integration

# Tear it down.
docker compose -f docker-compose.test.yml down
```

The compose file pins `livekit/livekit-server:v1.7` and runs it with `--dev`,
which seeds the credentials the fixtures expect:

| Setting | Value |
|---------|-------|
| `LIVEKIT_URL` | `ws://localhost:7880` |
| `LIVEKIT_API_KEY` | `devkey` |
| `LIVEKIT_API_SECRET` | `secret` (32-char dev default) |

Override any of these via environment variables before invoking pytest if
you point the suite at a different server.

## Health check

The compose service has a wget-based health check on
`http://127.0.0.1:7880/`. `docker compose ps` shows `healthy` once the
server is ready. The `livekit_dev_server` fixture additionally TCP-probes
the host:port pair and skips the test (rather than failing) when nothing
answers — so a forgotten `docker compose up` produces "skipped", not noise.

## Files in this directory

- `conftest.py` — `LiveKitDevServer` dataclass and the `livekit_dev_server`
  session-scoped fixture. Reads `LIVEKIT_*` env vars and applies the dev
  defaults when unset.
- `test_dev_server_fixture.py` — verifies the fixture itself (skip behavior
  when nothing is up, dataclass shape).
- `test_concurrent_real_calls.py` — the §8.5 acceptance test for concurrent
  real calls in one coroutine worker.

Add new integration tests in this directory and mark them with
`@pytest.mark.integration` (see `pyproject.toml` for the marker
registration). The marker is configured to opt-in: a bare `pytest` run
deselects the integration tests so unit-test loops stay fast.
