---
name: OpenRTC Web
description: The mahimai.ca signal-on-black world applied to OpenRTC's two surfaces, the five-page docs (Read) and the landing page (Persuade).
colors:
  signal: "#cba6f7"
  signal-deep: "#b48adc"
  on-signal: "#0a0a0a"
  ok: "#86efac"
  warn: "#fcd34d"
  ground: "#0a0a0a"
  surface: "#141414"
  surface-2: "#1b1b1b"
  line: "#262626"
  line-strong: "#3a3a3a"
  ink: "#fafafa"
  ink-soft: "#d4d4d4"
  muted: "#a3a3a3"
  light-signal: "#6f3fb0"
  light-signal-deep: "#5b2f96"
  light-ground: "#fcfcfc"
  light-surface: "#f3f3f4"
  light-surface-2: "#ebebed"
  light-line: "#e3e3e6"
  light-line-strong: "#c9c9ce"
  light-ink: "#0a0a0a"
  light-ink-soft: "#2a2a2e"
  light-muted: "#55555c"
  light-ok: "#15803d"
  light-warn: "#a16207"
  terminal: "#0c0c0c"
  terminal-dim: "#8a8a8a"
typography:
  landing-display:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2.6rem, 5.4vw, 4.4rem)"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "-0.04em"
  display:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2.4rem, 5vw, 4rem)"
    fontWeight: 500
    lineHeight: 1.02
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2.1rem, 4.4vw, 3.2rem)"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.04em"
  chapter-head:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.8rem, 3.4vw, 2.6rem)"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.625rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  subtitle:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 500
    letterSpacing: "-0.03em"
  body:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.7
  lede:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "Space Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.4
  code:
    fontFamily: "JetBrains Mono Variable, ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.7
    fontFeature: "tnum"
  table-head:
    fontFamily: "JetBrains Mono Variable, ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.3
  console:
    fontFamily: "JetBrains Mono Variable, ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "0.78rem"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "tnum"
rounded:
  code: "4px"
  control: "0.4rem"
  button: "0.5rem"
  field: "0.6rem"
  panel: "0.75rem"
  frame: "0.875rem"
  pill: "999px"
spacing:
  gutter: "1rem"
  stack: "1rem"
  panel-pad: "0.9rem 1.1rem"
  chapter: "2rem"
  landing-chapter: "4.5rem"
  rail-gap: "4rem"
  measure: "46rem"
  shell: "76rem"
components:
  button-primary:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.on-signal}"
    rounded: "{rounded.button}"
    padding: "0 1.1rem"
    height: "2.75rem"
  button-primary-hover:
    backgroundColor: "{colors.signal-deep}"
  button-secondary:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button}"
    padding: "0 1.1rem"
    height: "2.75rem"
  install-line:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.code}"
    rounded: "{rounded.field}"
    padding: "0.35rem 0.35rem 0.35rem 1rem"
  copy-button:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    height: "2.1rem"
  callout:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel-pad}"
  code-block:
    backgroundColor: "{colors.surface}"
    typography: "{typography.code}"
    rounded: "{rounded.panel}"
    padding: "1rem 1.2rem"
  pager-link:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel-pad}"
  theme-toggle:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    size: "1.85rem"
  inline-code:
    backgroundColor: "{colors.surface-2}"
    rounded: "{rounded.code}"
    padding: "0.1em 0.35em"
  console:
    backgroundColor: "{colors.terminal}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.console}"
    rounded: "{rounded.frame}"
  code-compare:
    backgroundColor: "{colors.surface}"
    typography: "{typography.code}"
    rounded: "{rounded.frame}"
    padding: "1.1rem 1.25rem"
  feature-row:
    textColor: "{colors.ink-soft}"
    typography: "{typography.body}"
    padding: "1.25rem 0"
  bench-track:
    backgroundColor: "{colors.surface-2}"
    rounded: "{rounded.pill}"
    height: "0.7rem"
  bench-bar-openrtc:
    backgroundColor: "{colors.signal}"
    rounded: "{rounded.pill}"
    height: "0.7rem"
  bench-bar-baseline:
    backgroundColor: "{colors.line-strong}"
    rounded: "{rounded.pill}"
    height: "0.7rem"
---

# Design System: OpenRTC Web

## Overview

**Creative North Star: "The Well-Kept README"**

This is the mahimai.ca world (see `/home/user/mahimai.ca/DESIGN.md`, the parent system) applied to a Read surface. The parent is a night-shift engineering console: charcoal ground, one lavender signal, real measurements as the only ornament. OpenRTC keeps that palette, that type pairing and that restraint, and bends the composition toward reading: one column of prose at a fixed measure, hairlines between chapters, tables and code allowed the full column, and an on-page contents rail on wide screens. Nothing decorates; the proof is a real `openrtc top` capture and measured tables.

Density is low and even. Pages are long single columns, not dashboards. Every docs page has the same frame (sticky top bar, title and lede, MDX body, previous/next pager, edit link); only the docs home adds a lead-in with the install line and the terminal capture.

The landing page (`web/landing/`) is the same world bent toward persuading: the hero is the worker running: a short head over a simulated `openrtc top` console at full width, with a rail of four beats lit in sync. Then one-column chapters on a hairline (a routing diagram of calls reaching their agents, code before and after, the features ruled with their limits, the measured benchmark bars, a closing call to action). It adds no new colors, fonts or depth. Its motion is the console loop with its beats, and a dot riding each route in the diagram; both stop for reduced motion.

Both surfaces read one palette. The landing page takes its tokens, base elements and chrome (skip link, top bar, footer, mark, buttons, theme toggle, install line) from `web/shared/theme.css`, imported by `web/landing/src/styles/landing.css`; its components are `web/shared/Mark.astro`, `ThemeToggle.astro`, `ThemeScript.astro` (sets the theme before first paint) and `InstallCommand.astro`. The docs are a Fumadocs site: `web/docs/app/global.css` maps the same hex values onto Fumadocs' `--color-fd-*` tokens (dark under `.dark`, the default), loads the same two fonts, and draws the same mark (`web/docs/components/mark.tsx`); the sidebar, contents rail, search dialog and callouts are Fumadocs' own. In CSS the frontmatter slugs appear as `--bg` (ground), `--accent` (signal), `--accent-deep` (signal-deep) and `--on-accent` (on-signal); the rest keep their names, and the light values are the same properties under `:root[data-theme='light']`.

What differs from the parent: no dot-grid background texture (the ground is flat `ground`); the OpenRTC ring mark replaces the panther as the one identity device; tables stack into labelled rows on phones; a sticky contents rail tracks the section being read; the shell is 76rem, not 80rem; and a second row of page links scrolls under the top bar on narrow screens instead of a menu.

**Key Characteristics:**
- Flat charcoal ground, hairline rules, no texture and no shadows.
- One lavender signal for links, the primary action, the focus ring, the mark's live arc and bar, and the active contents-rail item.
- Space Grotesk 500 for everything readable; JetBrains Mono for code, flags, table headers and measurements.
- Prose held to a 46rem measure; tables and code blocks may take the whole column.
- Dark by default; light is the same roles with the signal deepened.
- One shared theme file for both surfaces; the landing page adds components, not tokens.

## Colors

A near-black neutral ramp with a single lavender signal and two quiet status hues.

### Primary
- **Signal Lavender** (`signal`; `light-signal` in light theme): links (underlined, underline at 40% signal), the primary button, the focus outline, text selection, the mark's live arc and middle bar, the active contents-rail border, and `accent-color` on native controls. Pressed and hover state steps to **Pressed Lavender** (`signal-deep` / `light-signal-deep`). Text on a signal fill uses `on-signal`.

### Secondary
- **Ok Green** (`ok` / `light-ok`): only the copy button's done state.
- **Warn Amber** (`warn` / `light-warn`): only the warning callout's icon, and mixed at 35% into its border and 6% into its fill.

### Neutral
- **Ground** (`ground` / `light-ground`): page background and the fill of quiet controls (copy button, theme toggle track, secondary button).
- **Surface** (`surface` / `light-surface`): code blocks, callouts, blockquotes, the install line.
- **Surface Two** (`surface-2` / `light-surface-2`): inline code and the pressed theme-toggle segment.
- **Hairline** (`line` / `light-line`): chapter rules, table row rules, panel borders, the contents-rail track.
- **Strong Hairline** (`line-strong` / `light-line-strong`): table header rule, button and install-line borders, hover border on quiet controls, scrollbar thumb.
- **Ink** (`ink` / `light-ink`): headings, strong text, current nav item.
- **Soft Ink** (`ink-soft` / `light-ink-soft`): body prose and ledes.
- **Muted** (`muted` / `light-muted`): nav links at rest, table headers, list markers, pager captions, the mark's ring and quiet bars, feature limits, the star count.
- **Terminal** (`terminal`, both themes): the fill of the docs capture frame and the landing console. Inside the console the neutral ramp is literal dark values, with **Terminal Dim** (`terminal-dim`) for session ids, tenants, column heads, timestamps and the key hints.

### Named Rules
**The One Signal Rule.** Lavender marks links, the primary action, focus and data marks only (the mark's live arc, the console's `[reload]` tag, OpenRTC's benchmark bar). Never rules, headings, labels or decoration. One primary button per viewport.

**The Tokens-Only Rule.** Components read colors through the custom properties so both themes follow. The only literal colors are in the terminal frame and the landing console, which stay dark in both themes because they frame a dark terminal.

## Typography

**Display Font:** Space Grotesk Variable (with ui-sans-serif, system-ui)
**Body Font:** Space Grotesk Variable
**Label/Mono Font:** JetBrains Mono Variable (with ui-monospace, SF Mono, Menlo)

**Character:** A tight, slightly technical grotesk carries every heading and sentence at weight 500 or 400; the mono appears only where the content is literally code, a flag or a number.

### Hierarchy
- **Landing display** (500, clamp(2.6rem, 5.4vw, 4.4rem), 1, -0.04em): the landing H1 only, capped at 14ch.
- **Display** (500, clamp(2.4rem, 5vw, 4rem), 1.02, -0.04em): the docs home H1 only, capped at 15ch.
- **Headline** (500, clamp(2.1rem, 4.4vw, 3.2rem), 1.05, -0.04em): each doc page's H1.
- **Chapter head** (500, clamp(1.8rem, 3.4vw, 2.6rem), 1.08, -0.035em): landing chapter H2s, each with a soft-ink paragraph (1.0625rem / 1.65) under it inside a 46rem head block.
- **Title** (500, 1.625rem, 1.2): MDX H2, the chapter heads the contents rail lists.
- **Subtitle** (500, 1.125rem): MDX H3, indented one step in the rail.
- **Body** (400, 1rem, 1.7): prose in soft ink, at most 46rem wide. Ledes run 1.0625rem to 1.15rem.
- **Label** (500, 0.8125rem to 0.875rem): nav, pager captions, rail links, figure captions, footer.
- **Code** (400, 0.8125rem blocks / 0.875em inline, tabular numerals): code, flags, commands, measurements.
- **Table head** (mono 500, 0.75rem): table column headers and, on phones, the per-cell labels (0.6875rem).
- **Console** (mono 400, 0.78rem, 1.55, tabular numerals; 0.72rem on phones): everything inside the landing console.

### Named Rules
**The Mono-Means-Literal Rule.** JetBrains Mono is for things you could type or measure: code, flags, the install command, numbers (star counts, benchmark values), the console, and the column names of data tables. Prose labels stay in Space Grotesk.

**The Balanced Heading Rule.** H1 to H3 are weight 500, tracked -0.03em or tighter, with `text-wrap: balance`.

## Layout

A centered shell of `min(100% - 2rem, 76rem)` gives a 16px gutter on phones. Doc pages are one column; at 68rem and up the article gains a 13rem contents rail to its right with a 4rem gap. Prose children of the MDX body cap at 46rem; tables and code blocks may use the article's full width. The body stacks on a 1rem rhythm, with 2rem above each H2.

The top bar is sticky at 3.75rem. From 52rem up the five page links sit inline; below that they move to a second, horizontally scrolling row with a faded right edge, and the current page is scrolled into view. The home lead-in is one column, then splits 0.9fr / 1.1fr at 68rem with the terminal capture on the right; on phones the capture follows the lede.

Tables scroll horizontally on wide screens (numbers right-aligned in tabular figures) and, at 40rem and below, stack: each row becomes a block, each cell carries its column name as a small mono label above its value, and the first unlabeled cell reads as the row's title.

The landing hero is a short head (the H1, capped at 13ch, beside the lede, actions and install line, split 1.15fr / 0.85fr at 64rem and aligned to the baseline) over the story: the console at full width with a 17rem rail of four numbered beats beside it at 64rem, stacked below it on phones. The lede caps at 30rem. Below the hero, every chapter is a full-shell section with 4.5rem block padding and a 1px `line` rule on top; its head block (H2 and paragraph) caps at 46rem with 2.5rem below. Inside chapters: the before/after code splits 1.25fr / 1fr at 64rem; the features list becomes three columns (11rem name, 1.3fr what it does, 1fr limit) at 56rem; the benchmark chapter puts its head and its bars side by side at 64rem with a 4rem gap. On the landing page the top bar has no second row: below 52rem the page links fold away and only the mark, the GitHub pill and the theme toggle remain. The shared footer goes two columns at 48rem.

**The Rail Rule.** The contents rail appears only on wide screens and only when a page has more than two H2/H3 headings. It is sticky, lists H2 and H3, and marks the section in view with a signal left border.

## Elevation & Depth

Flat. There are no drop shadows. Depth comes from tonal steps (ground, surface, surface-2) and hairline borders. The sticky top bar is the only translucent layer: ground at 88% with a 12px backdrop blur and a hairline below. The pressed theme-toggle segment uses an inset 1px hairline ring, not a shadow.

**The Hairline-Not-Shadow Rule.** Separate things with a 1px `line` rule or a step to `surface`; never with a shadow.

## Shapes

Soft, small corners that grow with the object: inline code 4px, copy button 0.4rem, buttons 0.5rem, install line 0.6rem, panels (code blocks, callouts, blockquotes, pager links) 0.75rem, the terminal frame 0.875rem. The GitHub link and theme toggle are full pills. Borders are always 1px.

The OpenRTC mark is the one recurring geometry: a ring (radius 9.2 in a 24-unit box, 2.2 stroke, muted) with a quarter arc from twelve to two o'clock in the signal (2.6 stroke, round caps), and inside it three rounded bars of a voice level, the tall middle one in the signal. It stands for one worker with one call live, and reads as the O of OpenRTC. It appears in the top bar and the footer at 1.3rem; the favicon is the same drawing on a charcoal rounded square.

## Components

### Buttons
- **Shape:** gently rounded (0.5rem), 2.75rem tall, 1.1rem side padding, Space Grotesk 500 at 0.9375rem.
- **Primary:** signal fill, on-signal text, no border; hover steps to pressed lavender.
- **Secondary:** transparent with a strong hairline border and ink text; hover lifts the border to muted.
- **Focus:** the global 2px signal outline, 3px offset.
- **Count:** the landing "Star on GitHub" primary carries the live star count in mono 0.8125rem after a hairline divider (on-signal at 25%); it is absent when the count is.

### Install line
The home page's command: a surface field with a strong hairline and 0.6rem corners, the command in mono with a muted `$`, and a copy button at its right end. The copy button is a quiet ground-filled control (hairline border, 0.4rem corners) whose label flips to "Copied" in ok green for 1.6s.

### Callouts (Note, Tip, Warning)
A 0.75rem panel on surface with a hairline border, a 16px lucide-shaped icon in the signal, and body text at 0.9375rem. Warning swaps the icon to amber and tints border and fill with warn.

### Code blocks
Surface panel, hairline border, 0.75rem corners, JetBrains Mono 0.8125rem / 1.7, horizontal scroll. Shiki writes both themes as variables; the page picks the one matching `data-theme`.

### Tables
Mono muted headers over a strong hairline, hairline row rules, 0.875rem tabular figures, right-aligned numeric columns. Stack into labelled rows on phones (see Layout).

### Navigation
- **Top bar (docs):** mark and "OpenRTC" wordmark (600), five page links in muted that turn ink on hover and when current, a pill GitHub link, and the three-way theme toggle (light, dark, match system) stored in `localStorage['openrtc-theme']` and applied before first paint.
- **Top bar (landing):** the same bar with three links (Docs, Benchmark, Changelog) that fold away below 52rem; the GitHub pill shows the star count in muted mono 0.75rem after a hairline.
- **Contents rail:** "On this page" in ink 500, links in muted on a hairline track, current item ink with a signal border.
- **Pager:** previous/next as two hairline-bordered 0.75rem panels, muted caption over an ink label; the border strengthens on hover.

### Terminal frame (signature, docs)
A real capture (`openrtc top`) inside a 0.875rem frame that stays dark in both themes, with a hairline and a muted caption under it. It is the only image on the docs.

### Console (signature, landing)
The landing hero: `openrtc top` rebuilt in HTML on simulated sessions, always dark (terminal fill, 1px #262626 hairlines, 0.875rem corners, console type). A header line (title in ink 600, sessions, worker MB, load), the session table (dim ids and tenants, right-aligned numbers, `active` in ok green, `slow` in warn amber with the row tinted at 7% amber), a three-line log, and a key-hint footer. Below the frame, a muted 0.8125rem caption that begins "Simulated." On phones (34rem and below) the tenant and memory columns drop. The screen is one `role="img"` with a label describing the story; its parts are `aria-hidden`.

It plays one 16-second loop, one tick per second: a call arrives, a call turns slow, a save hot-reloads the agent (the log's `[reload]` tag is the signal) and the call recovers, a call ends. New rows and log lines use the page's only animation, `arrive`. The loop runs only while the console is on screen.

**The One Story Rule.** Motion tells one story and nothing else moves. The console loops through four beats (a call blocks the loop, the fix is saved and hot-reloaded, a call arrives, a call ends); the numbered rail beside it lights the current beat. New rows and log lines arrive over 0.6s (opacity from 0 and a 3px blur, ease-out-expo). In the routing diagram a dot rides each route every few seconds. Everything else changes only color on hover. Under `prefers-reduced-motion: reduce`, or without JavaScript, the console holds its opening frame (the slow call, beat one lit) and the diagram shows no dots; both are complete without motion.

### Before and after
Two code panes on surface with a hairline and 0.875rem corners, mono 0.8125rem / 1.75, each under a muted 0.875rem pane label. Shiki writes both themes; the page picks the one matching `data-theme`.

### Features list (landing)
A ruled definition list: each row has a hairline above it (and the last one below), 1.25rem block padding, the feature name in ink 500 at 1.0625rem, what it does in soft ink, and its limit in muted at 0.9375rem. No cards, no icons.

**The Limit-Beside-Feature Rule.** Every capability row states the limit that comes with it, in the same row and in muted. A feature without a known limit does not get a row until it has one.

### Benchmark bars (landing)
Each measure is a figure: an ink 500 caption with its unit in muted, then one row per system (8.5rem soft-ink name, a 0.7rem pill track in surface-2, a 3rem right-aligned mono value). Bars are drawn to a stated maximum, so widths compare honestly.

**The Signal-Is-Us Rule.** Only OpenRTC's bar takes the signal; every baseline bar is `line-strong`. It stays lavender where OpenRTC loses (CPU), because the color names the subject, not the winner.

### Star count
**The Fetched-Or-Absent Rule.** The GitHub star count is read from the GitHub API at build time. If the fetch fails, the count is not rendered at all; never a hard-coded or cached number.

## Do's and Don'ts

### Do:
- **Do** keep user-visible proof real: terminal captures and measured tables, with the method stated in the prose.
- **Do** hold prose to the 46rem measure and let tables and code take the full column.
- **Do** use the ring mark as the only identity device, with the arc and the middle bar as its only lit parts.
- **Do** make every new table stack into labelled rows at 40rem and below.
- **Do** read colors through the theme tokens so light and dark both follow.
- **Do** add shared tokens, chrome and components to `web/shared/` so the docs and the landing page stay one system.
- **Do** caption any simulated view as simulated, in its first word.
- **Do** give every landing capability its limit, and every comparison bar a stated maximum.
- **Do** hold the console's first frame under reduced motion or without JavaScript.

### Don't:
- **Don't** add the parent site's dot-grid texture or any other background pattern; the ground is flat.
- **Don't** add drop shadows; use a hairline or a surface step.
- **Don't** use lavender on rules, headings, labels or decoration.
- **Don't** add eyebrow or kicker labels above headings, or section numbers.
- **Don't** add abstract illustration; use a real capture, a labelled simulation of the real tool, or no picture.
- **Don't** animate anything outside the console, and don't loop the console while it is off screen.
- **Don't** give a baseline system the signal color in a comparison.
- **Don't** hard-code a star count or reintroduce unsourced density claims; show a number only if it was fetched or measured.
- **Don't** use em dashes in site copy.
