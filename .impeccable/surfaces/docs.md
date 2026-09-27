---
version: 1
slug: "docs"
primary_target: "docs"
related_targets: ["site"]
---

Scope: the OpenRTC docs site (site/, rendering docs/*.mdx). Visitor mode: Read.

Audience and job: an engineer who already runs livekit-agents, deciding in minutes whether OpenRTC changes their agent code (no) and what it gives them to run the worker. Proof: the real `openrtc top` output, measured PSS/CPU numbers against livekit-agents 1.8.3, and code that runs unchanged.

Constraints: five pages (Why OpenRTC, How it works, CLI, Benchmark, Changelog). Inherit the prices.mahimai.ca / mahimai.ca world. Static build on Cloudflare Workers at docs.openrtc.tech. No em dashes.

## Direction contract

THESIS: A docs site that reads like a well-kept README: one column, the problem first, numbers with their method, limits beside every feature. It refuses the docs-template default of a three-pane sidebar of forty stub pages and card grids of features.

OWN-WORLD: Charcoal ground, hairline rules, one lavender signal for links, actions and data. Space Grotesk 500 headings with tight tracking, JetBrains Mono only for code, flags and measurements. Tables with mono headers and right-aligned tabular numerals. Callouts border-only. The OpenRTC mark: four dots in a rounded frame, one lit in the signal.

STORY: The reader learns their Agent classes stay as they are, sees one pool route calls to them, sees `openrtc top` inspecting live sessions, reads the honest benchmark (3x less memory per call, not more calls per box), then installs.

FIRST VIEWPORT: Top bar (mark, five page links, GitHub, theme). Left: H1 "Every LiveKit agent, one worker you can see into", one-paragraph lede, install command in mono with a copy action, links to How it works and Benchmark. Right on wide screens: the real `openrtc top` capture, framed as a terminal. On mobile the capture follows the lede.

FORM: brief-pinned (the user asked for the voice-prices site pattern), so no concept roll: the prices.mahimai.ca MDX doc page, with an on-page contents rail on wide screens.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
