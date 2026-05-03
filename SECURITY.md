# Security policy

## Supported versions

OpenRTC is in active 0.1.x development. Security fixes land on the latest
0.1.x patch release; older minors do not receive backports.

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes (latest patch) |
| 0.0.x   | No (superseded by 0.1.0) |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Use one of:

1. **GitHub Security Advisories** (preferred):
   <https://github.com/mahimailabs/openrtc/security/advisories/new>.
   Allows private discussion + a coordinated CVE if warranted.
2. **Email** the maintainer at `hello@mahimai.dev` with the subject
   prefix `[openrtc-security]`.

Include:

- A short description of the issue.
- Reproduction steps or a minimal proof-of-concept.
- Affected version(s) (`pip show openrtc`).
- Your assessment of severity / impact (best guess is fine).

## What to expect

- Acknowledgement within **3 business days**.
- A first triage assessment (severity, scope, fix plan) within
  **7 business days**.
- A patch release timeline communicated once the issue is reproduced.
- Public disclosure (advisory + changelog entry) coordinated with the
  reporter, typically after the patch release ships.

This is a single-maintainer project. Response times are best-effort and
may extend during travel or peak workload; high-severity reports
(remote code execution, credential exfiltration, persistent
denial-of-service) are prioritized.

## Out of scope

Issues that do not constitute a vulnerability in OpenRTC itself:

- Issues in upstream `livekit-agents`, `livekit`, or any plugin
  (report directly to the upstream project).
- Misconfiguration in the operator's deployment (e.g. exposing LiveKit
  API secrets in logs by adding `--log-level=DEBUG` in production).
- Denial-of-service via deliberately exhausting `max_concurrent_sessions`
  on a single worker (this is the documented backpressure mechanism;
  use horizontal scaling).
