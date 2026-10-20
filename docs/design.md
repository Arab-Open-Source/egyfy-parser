# Design Notes

EgyFy Parser is a document workspace, not a dashboard. The interface exists to
answer three questions at a glance: what document is open, how the model read
it, and what the result will look like when exported.

The rules below explain the intent behind the interface. The implementation
lives in `static/style.css`; this document is the reference for changing it.

## Principles

1. **The document leads.** The page preview and extracted text receive the
   strongest contrast and the most space. Controls stay in a fixed, narrow
   column so the document never shifts when settings change.
2. **One accent.** Forest green marks actions, selected states, and the current
   focus. Layout colors are reserved for the overlay legend, where color
   carries meaning rather than decoration.
3. **Evidence, not atmosphere.** There are no gradients, glows, scan beams,
   glass panels, or simulated terminal output. Confidence values, timings, and
   source labels are shown plainly because they help judge the result.
4. **Quiet chrome.** Borders are hairlines, shadows are shallow, and radii stay
   small. The interface should look assembled from paper, ink, and ruled lines.
5. **State is always explained.** Empty, busy, complete, and failed states each
   have a sentence in the status line and, where useful, a toast. No spinner
   runs without a label.

## Color

| Role | Light | Dark |
| --- | --- | --- |
| Canvas | `#f6f6f3` | `#141613` |
| Surface | `#ffffff` | `#1b1e1a` |
| Muted surface | `#efefe9` | `#232720` |
| Border | `#e2e2da` | `#30352d` |
| Strong border | `#c8c8be` | `#474e43` |
| Text | `#1a1c18` | `#eceee8` |
| Secondary text | `#565b52` | `#b6bbae` |
| Muted text | `#7d8278` | `#8a9082` |
| Accent | `#1f6b4f` | `#7ec9a7` |
| On accent | `#ffffff` | `#0d1a13` |
| Danger | `#b42318` | `#f97066` |

The interface follows the operating system preference until the user chooses a
theme. The dark palette is a separate set of tokens, not an inverted filter.
The choice is stored in `localStorage` under `egyfy.theme` and applied before
the first paint to avoid a flash.

## Typography

- **Interface:** the system sans-serif stack at 14px/1.5. Section labels are
  10.5px, uppercase, and letter-spaced; body copy in controls is 12–13px.
- **Document preview:** Iowan Old Style, Palatino, Georgia, and Times fall back
  in that order, at 15.5px/1.72. This distinguishes machine output from the
  controls that produced it.
- **Data:** the system monospace stack is used for page numbers, timings,
  confidence values, and file extensions. It is never used for prose.
- Headings use tight tracking (`-0.015em`); body text does not.

## Layout

- A 56px sticky header holds the brand, engine version, live status, and the
  theme and repository actions.
- The 300px settings column is sticky above 900px and scrolls independently.
  It is ordered by frequency of use: document, extraction, overlays,
  performance, privacy.
- The content area is capped at 1600px. Each page is a card with a two-column
  body: visual preview on the left, extracted content on the right.
- The split becomes one column at 1120px. The settings column moves above the
  content at 900px. Below 620px the toolbar wraps and the header sheds the
  engine version.
- Spacing runs on a 2px base with 4, 6, 8, 10, 12, 16, 20, and 22px steps in
  dense areas, and 22–30px between sections.

## Components

- **Dropzone.** A dashed rectangle on a muted surface. On hover or drag it
  takes the accent tint. The whole area is a label, so clicking, dropping, and
  keyboard activation all open the file picker.
- **Segmented control.** Used only for the three reading modes. The selected
  option is a raised surface with a hairline shadow, never a filled accent.
- **Switches.** A 32×18px track with a 12px thumb. The input remains in the
  accessibility tree and the track receives the focus ring.
- **Buttons.** One filled primary action per view (Export). Secondary actions
  use a bordered or ghost treatment. Destructive actions use the danger token.
- **Page card.** Header, preview, and tabs form one unit. Tabs switch between
  rendered preview, raw Markdown, line confidences, and JSON. Overlay controls
  hide layers through classes on the workspace, not by rebuilding the SVG.
- **Overlays.** Line boxes use the accent at low weight. Layout blocks use the
  legend colors, with labels drawn in the same color over a white stroke for
  legibility on scans. Reading order is a thin path with numbered dots.
- **Lightbox.** The full page is shown at its intrinsic size, capped to the
  viewport. It closes with the close button, the backdrop, or Escape, and
  returns focus to the trigger.
- **Menus and toasts.** Menus are anchored panels with a hairline border and a
  short fade. Toasts sit above the content on the right and disappear after
  roughly three seconds.

## Motion

Transitions are 150ms with `cubic-bezier(0.2, 0.7, 0.2, 1)`. Motion is limited
to color, opacity, small translations, and the switch thumb. The spinner is
used only while work is in progress. `prefers-reduced-motion` reduces all
durations to near zero.

## Accessibility

- All controls are native buttons, labels, or inputs with visible focus rings.
- Icon-only buttons carry `aria-label` and a `title`.
- The status line is a live region; toasts are announced politely.
- Tabs expose `role="tab"` and `aria-selected`, and panels are hidden rather
  than removed.
- The lightbox is a modal dialog with a labelled close button and focus return.
- Text in the document is rendered with `dir="auto"` so right-to-left and
  mixed-direction pages keep their reading direction.
- Color is never the only signal: confidence values carry a `.low` class and
  the source badge always has a text label.

## Copy

Labels are short and literal: “Choose a file”, “Apply and re-run”, “Copy
Markdown”. Helper text explains a consequence, not a mechanism: “Slower on
pages with formulas” is useful; “Invokes the math recognizer” is not. Avoid
exclamation marks, exclamation-style success messages, and claims the interface
cannot verify.
