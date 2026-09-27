---
version: 1
slug: "landing"
primary_target: "landing"
related_targets: ["web/landing"]
---

Scope: the OpenRTC landing page (web/landing/, openrtc.tech). Visitor mode: Persuade.

Audience and job: an engineer who runs, or is about to run, livekit-agents in production and lands here from GitHub, PyPI, or a post. In one screen they should understand the offer (every agent in one pool, and a live view into the worker) and act. Primary action: Star on GitHub. Secondary: Read the docs, and the install command with copy.

Proof, all real or labelled: the `openrtc top` view, simulated and labelled as such; code showing the agent class unchanged; the measured head-to-head against livekit-agents 1.8.3 (~22 vs ~63 MB PSS per call, CPU the limit), linking to the method. Constraints: the old openrtc-web claims (50+ sessions per worker, ~3 GB saved per agent, the density calculator, a hard-coded star count) are false or unsourced and must not return. A star count is shown only if fetched live at build time.

## Direction contract

THESIS: A product page that proves itself the way a trace does: the hero is the worker, running. It refuses the dev-tool landing default of a gradient hero, a glowing grid, and a row of big-number stats.

OWN-WORLD: The docs world (web/shared/theme.css): charcoal ground, hairlines, one lavender signal for actions, links and data marks. Space Grotesk 500 display with tight tracking, JetBrains Mono for the console, code and measured numbers. Chapters separated by a hairline on a 76rem shell. The OpenRTC mark.

STORY: The visitor sees calls running in one worker, one going slow, a save hot-reloading live calls; learns their Agent classes stay as written; sees the honest numbers (less memory per call, not more calls per box); stars the repo or opens the docs.

FIRST VIEWPORT: Top bar (mark, Docs, Benchmark, Changelog, GitHub with live stars, theme). Left: H1 "Every LiveKit agent, one worker you can see into", a two-sentence lede, primary "Star on GitHub", secondary "Read the docs", install command with copy. Right, larger than the copy: the `openrtc top` console animating, captioned "Simulated sessions". Mobile: console follows the actions.

FORM: brief-pinned by the user's answers (hero = live openrtc top, CTA = Star on GitHub, proof = honest benchmark strip), inside the established world, so no concept roll: hero console, then code, then capabilities with limits, then the benchmark band, then a closing call to action.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
