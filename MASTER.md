# MASTER — Degree Planner design system

Single source of truth. Every token lives in `frontend/src/App.css` (`@theme`) and `frontend/src/App.tsx` (`T` motion tokens). No rogue hex values elsewhere.

## Visual thesis
Warm-white Notion-style workspace: near-white canvas with a `#f7f7f5` panel tint, warm-charcoal ink, Inter/system sans at 13–14px with weight (not size) carrying hierarchy, airy 4px-grid spacing, flat 1px-bordered components with 6px radii, hairline dividers, one restrained blue accent, no drop shadows except popovers.

## Interaction thesis
Fast, dry, tween-only motion — 120ms micro / 200ms panel / 320ms diagram-layout — on `cubic-bezier(0.2, 0, 0, 1)`. Hover = background/border tint only. No scroll effects.
**Forbidden:** springs/bounce, scale-on-hover, shadow-on-hover, animating width/height/top/left.

## Color
| token | value | use |
|---|---|---|
| `canvas` | `#ffffff` | page + diagram background |
| `surface` | `#f7f7f5` | side panels, approved term bands |
| `surface-hover` | `#efefed` | hover fill on ghost buttons / rows |
| `line` | `#e9e9e7` | hairline borders, dividers |
| `line-strong` | `#c9c7c1` | hover borders, prerequisite edges |
| `ink` | `#37352f` | primary text |
| `ink-2` | `#787774` | secondary text (4.6:1 on white) |
| `ink-3` | `#9b9a97` | placeholders, decorative only (not body text) |
| `accent` / `accent-hover` | `#2563eb` / `#1d4ed8` | primary action, focused edges |
| `accent-soft` | `#eaf1fd` | proposed band tint |
| `success` / `success-soft` | `#0f7b4f` / `#e8f4ee` | approved courses, satisfied rules |
| `warning` / `warning-soft` | `#8a5a0b` / `#fbf5e6` | warnings, unverified prereqs |
| `danger` / `danger-soft` | `#c62828` / `#fdecec` | prerequisite violations |

## Typography
Inter → ui-sans-serif → system-ui. Sizes: 11px (eyebrow, uppercase, tracking-wide), 12px (meta), 13px (UI default), 14px (body/headings in panels). Weights: 400 body, 500 labels/buttons, 600 headings + course codes. `tabular-nums` on every number.

## Spacing
4px base. Scale used: 4, 8, 12, 16, 20, 24. Header 44px. Side panels 320px. Diagram card 170×56.

## Radii
`sm` 4px (badges) · `md` 6px (buttons, inputs, cards) · `lg` 8px (term bands) · `full` (dots, progress bar).

## Shadows
`shadow-1` = `0 0 0 1px rgb(15 15 15 / .06), 0 1px 2px rgb(15 15 15 / .04)` — reserved for future popovers/menus; nothing in the current UI casts a shadow.

## Motion
| token | duration | easing | use |
|---|---|---|---|
| `T.fast` | 120ms | `[0.2,0,0,1]` | hover/focus/toggle, list rows |
| `T.base` | 200ms | same | panels open/close, banners |
| `T.slow` | 320ms | same | diagram cards/bands re-layout, edge draw |
Exit = same easing, opacity-led, never longer than enter. `prefers-reduced-motion` collapses all to ~0.

## Components
- **Ghost button** (`btn`): 28px tall, transparent, hover `surface-hover`, active `line`, disabled 40%, focus ring `accent/40`.
- **Primary button** (`primary`): `accent` fill, white text, hover `accent-hover`.
- **Icon button** (`icon`): 28×28, `ink-2` → `ink` on hover, `surface-hover` fill.
- **Field** (`field`): 28px, `line` border → `line-strong` hover → `accent` focus.
- **Course card**: white, `line` border, `md` radius; proposed = dashed `line-strong`; violation = `danger` border + `danger-soft` fill; focused = `accent` border.
- **Term band**: approved = `surface` fill, no border; proposed = `accent-soft` fill, dashed `line-strong`; break term = `success-soft`.
- **Section line** (proposal card, under the reason): 12px `tabular-nums`, `MW 1:40PM–2:30PM · Instructor · +3 more`.
  `ink-2` normally; `warning` when every fitting section is full; `ink-3` and prefixed *usually* once the term is
  past the published schedule (a season pattern, not a booking); `ink-3` "no published schedule" when unknown.
  Never render a pattern time in `ink-2` — the colour is the only thing separating a fact from an estimate.
- **Availability control**: a `<details>` in the left panel. Two native `<input type="time">` fields (`field`, `w-26`)
  and five day toggles — 28px, `line-strong` border when available, `surface-hover` + `ink-3` + strike-through when
  not. An `on` badge (`tag`) in the summary whenever anything is narrowed, plus a ghost "Clear availability".
- **Advisor chat** (`Chat.tsx`): 320×420 card anchored bottom-right of the diagram, `canvas` fill, `line` border, `lg` radius,
  `shadow-1` (the one permitted popover shadow). 36px header with an `ink-3` uppercase "Gemini" eyebrow. Messages are 13px
  bubbles, `md` radius: student = `accent` fill + white text, right-aligned at ≤85%; advisor = `surface` fill. Input is a `field`,
  Send is a `primary` button. Enters with a 12px upward slide + fade on `T.base`; "Thinking…" in `ink-3` while waiting.

## Layout
`header (44px)` / `[left 320px | diagram flex-1 | right 320px]`; the Advisor chat floats over the diagram's bottom-right corner (toggled by the header **Advisor** button). Left = approval, right = requirements + Pathways. Panels toggle with header buttons, `Ctrl/⌘+[` and `Ctrl/⌘+]`; state persisted in `localStorage` (`ui:left`, `ui:right`).
