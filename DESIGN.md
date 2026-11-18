# cleanCT: design system

Source of truth in code: `src/theme.py`. Change a colour there, not in a widget.
`tests/test_theme.py` checks every text pair in both themes against WCAG AA
(4.5:1).

## Colour tokens

| Token | Dark | Light | Use |
|---|---|---|---|
| app | #15181d | #f1f3f5 | window ground |
| panel | #1b1f25 | #ffffff | sidebar, panels, lists |
| raised | #232830 | #e8ecf0 | fields, hovered rows, segmented groups |
| canvas | #0b0d10 | #0b0d10 | scan canvases (both themes) |
| line | #2b313a | #d6dce3 | dividers |
| line_strong | #3b4350 | #b8c1cc | control borders |
| text | #e8ebef | #14181d | primary text |
| text_2 | #aab2bd | #465060 | secondary labels |
| text_3 | #8b94a2 | #5f6977 | hints and captions |
| accent | #3fc6b6 | #0a7266 | cut lines, primary action, active state |
| on_accent | #0a1714 | #ffffff | text on accent |
| ok / warn / error / info | green / amber / red / blue | | status |

Viewer overlay colours (keep, cut and margin lines; wood and metal ROI) stay as
the viewers draw them. They are data, not chrome.

## Typography

- Body and labels: Segoe UI, 13 px. Captions and hints: 12 px.
- Titles and numbers: Bahnschrift (title 19 px, KPI values 17 px).
- Log: Cascadia Mono, falling back to Consolas, 12 px.
- Section headings (role `section`): 14 px, semibold.
- Sentence case everywhere. No all-caps labels.

## Layout

- Sidebar, 280 px: brand and GPU status, specimen list and filter, scan actions,
  checkpoints, preview history, the primary process buttons, and the Activity
  drawer at the bottom.
- Main area: title and subtitle, then the cut metrics strip, then the Auto and
  Boundaries tabs, then the export row, then the two viewers (and the 3-D panel
  on Auto).
- The Boundaries page keeps its controls on the right at 468 px.
- Minimum window width is about 1250 px. Each page scrolls sideways if the window
  is narrower than the page needs.

## Components

- **Buttons.** Secondary by default (outlined). `role="primary"`, or the named
  primary actions (`btn_process`, `btn_apply_prefs`, `btn_load_confirm`), are
  filled with the accent. `role="ghost"` is text only, for low-weight actions.
  `active="true"` marks the selected segment of a toggle group.
- **Focus.** Every control gets an accent border on keyboard focus.
- **Lists.** The specimen rows are painted by `widgets/specimen_panel.py`, using
  theme colours at paint time, so they follow the theme.
- **Activity drawer.** One line of the latest message stays visible. The full log
  opens with "Show activity".
- **Dialogs and menus** follow the same tokens through `theme.qss()`.

## Rules

- No pictographs or arrows inside button text.
- No em dashes in titles or labels. Use a colon or a full stop.
- Long explanations wrap onto more lines. An unwrapped sentence must not set the
  window's minimum width.
- Motion: none beyond Qt's defaults. Nothing animates on its own.
- The two themes change only the chrome. The scan canvas stays dark in both.
