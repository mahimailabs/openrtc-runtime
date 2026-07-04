---
title: openrtc top
description: htop-style live inspector for the shared-worker session pool (columns, key bindings, filters, and flags).
icon: table-list
---

# openrtc top

`openrtc top` is an `htop`-style live inspector for a running coroutine-mode
worker. It connects to the worker's private local socket and shows one row per
live session, refreshing in place.

![openrtc top](/public/openrtc-top.svg)

```bash
openrtc top                     # live view, 1 Hz
openrtc top --refresh-rate 2    # 2 Hz (allowed range 0.5–10)
openrtc top --once              # print one snapshot and exit (scripts / CI)
openrtc top --sort cpu_pct      # initial sort column
openrtc top --status slow       # only sessions currently blocking the loop
openrtc top --socket /path.sock # non-default socket (rarely needed)
```

<Note>
The inspector needs a **running coroutine-mode worker** on the same host
(`openrtc dev ./agents` or `openrtc start ./agents`). If none is serving the
socket, `openrtc top` prints a "no running openrtc pool" hint instead of a
traceback. Introspection is on by default; a worker started with
`enable_introspection=False`, or in `process` isolation, serves no socket.
</Note>

## Columns

| Column | Meaning |
| --- | --- |
| `session` | Session id (the LiveKit job id), truncated. |
| `agent` | The registered agent class handling the session. |
| `tenant` | `metadata["tenant"]`, or `-` when unset. |
| `dur(s)` | Seconds since the session went live. |
| `mem(MB)` | Current equal-share memory attribution. |
| `peak` | Highest memory share seen over the session's life. |
| `cpu%` | Share of sampled on-CPU time. |
| `status` | `active`, or `slow` when the session recently blocked the loop. |
| `pin` | `*` when pinned (reserved; see below). |

See [Session Introspection](/concepts/session-introspection) for exactly how
`mem(MB)`, `cpu%`, and `slow` are computed (and their sampling caveats).

## Key bindings

| Key | Action |
| --- | --- |
| `q` | Quit. |
| `r` | Refresh now. |
| `s` | Cycle the sort column (`mem_mb → cpu_pct → duration_s → agent → session`). |
| `f` | Cycle the status filter (`all → active → slow → draining → errored`). |

Numeric columns sort descending (biggest first, htop-style); text columns sort
ascending.

## Flags

| Flag | Default | Notes |
| --- | --- | --- |
| `--once` | off | Print a single snapshot and exit. Stable for scripts and CI. |
| `--refresh-rate` | `1.0` | Live refresh in Hz; clamped to 0.5–10. Ignored with `--once`. |
| `--sort` | `mem_mb` | Initial sort column; cycle live with `s`. |
| `--status` | `all` | Initial status filter; cycle live with `f`. |
| `--socket` | per-user default | The worker's introspection socket path. |

## Scope

Local pool only. Remote / production-cluster inspection and per-session
drill-down are out of scope for v0.3 (table view of the local worker only). For
cost, latency, and quality, use **voicegateway**, not `openrtc top`.
