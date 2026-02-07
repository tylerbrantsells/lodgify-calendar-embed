# Design Spark Calendar Style Guide (WIP)

## Palette
- Background: `#f7ead7`
- Panel: `#ffffff`
- Text: `#2a1f1a`
- Muted: `#6f625b`
- Grid: `#eadfcf`
- Brand Accent: `#f04c3a`
- Accent Soft: `#fde3d6`
- Reservation Fill: `#f7b6a3`
- Reservation Border: `#e2563f`
- Owner Block Fill: `#d4d1cc`
- Quick Turn: `#ffe49a`
- Weekend: `rgba(0,0,0,0.02)`

## Typography
- Base: `-apple-system`, `BlinkMacSystemFont`, `SF Pro Text`, `SF Pro Display`, `Helvetica Neue`, `Arial`
- Header Title: 17px / 600 weight
- Meta/Labels: 12px / 500 weight
- Day Cells: 12px (10px compact)

## Layout
- Row Height: 64px (52px compact)
- Header Height: 52px
- Half‑day cell width: 26px (24px compact)
- Pill Height: 26px (22px compact)
- Row Divider: `rgba(47, 42, 38, 0.12)` (2px)

### Mobile
- Left column width: 96px (≤720px), 84px (≤540px)
- Month header: short form with period (`Jan.`/`Feb.`/`Mar.`), no year. **May has no period**.
- Property labels: number + first 4 letters, capitalized (e.g., `111 Eagl`)

## Components
- Reservation pill: soft coral fill, coral border, white text, pill radius 14px.
- Owner block pill: light gray fill, muted border, dark text.
- Quick turn: yellow cell highlight.
- Occupied days: diagonal hatch overlay.
- Today: highlighted header cell only.

## Interaction
- Horizontal scroll for timeline (rolling 180 days).
- Prev/Next shift by 30 days.
- Today jumps and centers today in view.

## Motion
- None (intentionally minimal).
