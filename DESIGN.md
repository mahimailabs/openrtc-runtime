---
name: OpenRTC Docs
description: The mahimai.ca signal-on-black world applied to a five-page Read surface for OpenRTC.
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
typography:
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
---

# Design System: OpenRTC Docs

## Overview

**Creative North Star: "The Well-Kept README"**

This is the mahimai.ca world (see `/home/user/mahimai.ca/DESIGN.md`, the parent system) applied to a Read surface. The parent is a night-shift engineering console: charcoal ground, one lavender signal, real measurements as the only ornament. OpenRTC keeps that palette, that type pairing and that restraint, and bends the composition toward reading: one column of prose at a fixed measure, hairlines between chapters, tables and code allowed the full column, and an on-page contents rail on wide screens. Nothing decorates; the proof is a real `openrtc top` capture and measured tables.

Density is low and even. Pages are long single columns, not dashboards. Every page has the same frame (sticky top bar, title and lede, MDX body, previous/next pager, edit link); only the home page adds a lead-in with the install line and the terminal capture.

What differs from the parent: no dot-grid background texture (the ground is flat `ground`); the four-dot OpenRTC mark replaces the panther as the one identity device; tables stack into labelled rows on phones; a sticky contents rail tracks the section being read; the shell is 76rem, not 80rem; and a second row of page links scrolls under the top bar on narrow screens instead of a menu.

**Key Characteristics:**
- Flat charcoal ground, hairline rules, no texture and no shadows.
- One lavender signal for links, the primary action, the focus ring, the live mark dot and the active contents-rail item.
- Space Grotesk 500 for everything readable; JetBrains Mono for code, flags, table headers and measurements.
- Prose held to a 46rem measure; tables and code blocks may take the whole column.
- Dark by default; light is the same roles with the signal deepened.

## Colors

A near-black neutral ramp with a single lavender signal and two quiet status hues.

### Primary
- **Signal Lavender** (`signal`; `light-signal` in light theme): links (underlined, underline at 40% signal), the primary button, the focus outline, text selection, the lit dot of the mark, the active contents-rail border, and `accent-color` on native controls. Pressed and hover state steps to **Pressed Lavender** (`signal-deep` / `light-signal-deep`). Text on a signal fill uses `on-signal`.

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
- **Muted** (`muted` / `light-muted`): nav links at rest, table headers, list markers, pager captions, the unlit mark dots and frame.

### Named Rules
**The One Signal Rule.** Lavender marks links, the primary action, focus and live data only. Never rules, headings, labels or decoration. One primary button per viewport.

**The Tokens-Only Rule.** Components read colors through the custom properties so both themes follow. The only literal colors are in the terminal frame, which stays dark in both themes because it frames a dark capture.

## Typography

**Display Font:** Space Grotesk Variable (with ui-sans-serif, system-ui)
**Body Font:** Space Grotesk Variable
**Label/Mono Font:** JetBrains Mono Variable (with ui-monospace, SF Mono, Menlo)

**Character:** A tight, slightly technical grotesk carries every heading and sentence at weight 500 or 400; the mono appears only where the content is literally code, a flag or a number.

### Hierarchy
- **Display** (500, clamp(2.4rem, 5vw, 4rem), 1.02, -0.04em): the home H1 only, capped at 15ch.
- **Headline** (500, clamp(2.1rem, 4.4vw, 3.2rem), 1.05, -0.04em): each doc page's H1.
- **Title** (500, 1.625rem, 1.2): MDX H2, the chapter heads the contents rail lists.
- **Subtitle** (500, 1.125rem): MDX H3, indented one step in the rail.
- **Body** (400, 1rem, 1.7): prose in soft ink, at most 46rem wide. Ledes run 1.0625rem to 1.15rem.
- **Label** (500, 0.8125rem to 0.875rem): nav, pager captions, rail links, figure captions, footer.
- **Code** (400, 0.8125rem blocks / 0.875em inline, tabular numerals): code, flags, commands, measurements.
- **Table head** (mono 500, 0.75rem): table column headers and, on phones, the per-cell labels (0.6875rem).

### Named Rules
**The Mono-Means-Literal Rule.** JetBrains Mono is for things you could type or measure: code, flags, the install command, numbers, and the column names of data tables. Prose labels stay in Space Grotesk.

**The Balanced Heading Rule.** H1 to H3 are weight 500, tracked -0.03em or tighter, with `text-wrap: balance`.

## Layout

A centered shell of `min(100% - 2rem, 76rem)` gives a 16px gutter on phones. Doc pages are one column; at 68rem and up the article gains a 13rem contents rail to its right with a 4rem gap. Prose children of the MDX body cap at 46rem; tables and code blocks may use the article's full width. The body stacks on a 1rem rhythm, with 2rem above each H2.

The top bar is sticky at 3.75rem. From 52rem up the five page links sit inline; below that they move to a second, horizontally scrolling row with a faded right edge, and the current page is scrolled into view. The home lead-in is one column, then splits 0.9fr / 1.1fr at 68rem with the terminal capture on the right; on phones the capture follows the lede.

Tables scroll horizontally on wide screens (numbers right-aligned in tabular figures) and, at 40rem and below, stack: each row becomes a block, each cell carries its column name as a small mono label above its value, and the first unlabeled cell reads as the row's title.

**The Rail Rule.** The contents rail appears only on wide screens and only when a page has more than two H2/H3 headings. It is sticky, lists H2 and H3, and marks the section in view with a signal left border.

## Elevation & Depth

Flat. There are no drop shadows. Depth comes from tonal steps (ground, surface, surface-2) and hairline borders. The sticky top bar is the only translucent layer: ground at 88% with a 12px backdrop blur and a hairline below. The pressed theme-toggle segment uses an inset 1px hairline ring, not a shadow.

**The Hairline-Not-Shadow Rule.** Separate things with a 1px `line` rule or a step to `surface`; never with a shadow.

## Shapes

Soft, small corners that grow with the object: inline code 4px, copy button 0.4rem, buttons 0.5rem, install line 0.6rem, panels (code blocks, callouts, blockquotes, pager links) 0.75rem, the terminal frame 0.875rem. The GitHub link and theme toggle are full pills. Borders are always 1px.

The OpenRTC mark is the one recurring geometry: a 20-unit rounded square frame (radius 5, 1.6 stroke, muted) holding a 2x2 grid of dots, the top-left dot lit in the signal. It stands for four agents in one worker, one of them live. It appears in the top bar and the footer at 1.15rem.

## Components

### Buttons
- **Shape:** gently rounded (0.5rem), 2.75rem tall, 1.1rem side padding, Space Grotesk 500 at 0.9375rem.
- **Primary:** signal fill, on-signal text, no border; hover steps to pressed lavender.
- **Secondary:** transparent with a strong hairline border and ink text; hover lifts the border to muted.
- **Focus:** the global 2px signal outline, 3px offset.

### Install line
The home page's command: a surface field with a strong hairline and 0.6rem corners, the command in mono with a muted `$`, and a copy button at its right end. The copy button is a quiet ground-filled control (hairline border, 0.4rem corners) whose label flips to "Copied" in ok green for 1.6s.

### Callouts (Note, Tip, Warning)
A 0.75rem panel on surface with a hairline border, a 16px lucide-shaped icon in the signal, and body text at 0.9375rem. Warning swaps the icon to amber and tints border and fill with warn.

### Code blocks
Surface panel, hairline border, 0.75rem corners, JetBrains Mono 0.8125rem / 1.7, horizontal scroll. Shiki writes both themes as variables; the page picks the one matching `data-theme`.

### Tables
Mono muted headers over a strong hairline, hairline row rules, 0.875rem tabular figures, right-aligned numeric columns. Stack into labelled rows on phones (see Layout).

### Navigation
- **Top bar:** mark and "OpenRTC" wordmark (600), five page links in muted that turn ink on hover and when current, a pill GitHub link, and the three-way theme toggle (light, dark, match system) stored in `localStorage['openrtc-theme']` and applied before first paint.
- **Contents rail:** "On this page" in ink 500, links in muted on a hairline track, current item ink with a signal border.
- **Pager:** previous/next as two hairline-bordered 0.75rem panels, muted caption over an ink label; the border strengthens on hover.

### Terminal frame (signature)
A real capture (`openrtc top`) inside a 0.875rem frame that stays dark in both themes, with a hairline and a muted caption under it. It is the only image on the site.

## Do's and Don'ts

### Do:
- **Do** keep user-visible proof real: terminal captures and measured tables, with the method stated in the prose.
- **Do** hold prose to the 46rem measure and let tables and code take the full column.
- **Do** use the four-dot mark as the only identity device, with exactly one dot lit.
- **Do** make every new table stack into labelled rows at 40rem and below.
- **Do** read colors through the theme tokens so light and dark both follow.

### Don't:
- **Don't** add the parent site's dot-grid texture or any other background pattern; the ground is flat.
- **Don't** add drop shadows; use a hairline or a surface step.
- **Don't** use lavender on rules, headings, labels or decoration.
- **Don't** add eyebrow or kicker labels above headings, or section numbers.
- **Don't** add abstract illustration; use a real capture or no picture.
- **Don't** use em dashes in site copy.
