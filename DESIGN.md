# cleanCT: design system

Source of truth in code: `src/theme.py`. Change a colour there, not in a widget.
`tests/test_theme.py` checks every text pair in both themes against WCAG AA
(4.5:1). `tests/test_theme_tokens.py` fails on a hex colour typed into any file
except `theme.py` and the viewers. `tests/test_dialogs.py` checks each dialog's
ground and copy in both themes.

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
- Main area: title and subtitle, then the cut metrics strip, then the tab row
  (Auto and Boundaries on the left, Settings on the right), then the export row,
  then the two viewers (and the 3-D panel on Auto).
- The export row shows where the bundle goes (the path is elided, its full text
  in the tooltip), the format, a "Change in Settings" link and Export bundle. The
  folder and format are set on Settings, not in this row.
- Every page fits a 1280x720 client without a vertical scroll bar
  (`tests/test_layout_fit.py`). The tab bar, the header and the KPI strip are
  kept compact to meet that.
- The Boundaries control column (468 px) shows one of three segments at a time:
  Lines, Display (palette and thresholds), Lateral box. The range summary and
  the apply row stay pinned under the segments.
- The Settings page has a left rail of four sections (Appearance, Export,
  Checkpoints, Shortcuts), 200 px wide. The chosen section shows as a card of at
  most 760 px. Every choice is saved as it changes; there is no Save button.
- Minimum window width is 1280 px, the supported width. Each page still scrolls
  sideways if a window is narrower than the page needs.

## Components

- **Buttons.** Secondary by default (outlined). `role="primary"`, or the named
  primary actions (`btn_process`, `btn_apply_prefs`, `btn_load_confirm`), are
  filled with the accent. `role="ghost"` is text only, for low-weight actions.
  `active="true"` marks the selected segment of a toggle group.
- **Focus.** Every control gets an accent border on keyboard focus.
- **Workspace tabs.** `role="tab"`: text tabs on one baseline. The active tab is
  `text` colour with a 2 px accent underline. Settings sits at the right end.
- **Segments.** `role="segment"`: a compact group of choices inside a panel
  (the Boundaries groups). The active segment takes the accent fill.
- **Groups in a panel.** `box_card` and `box_lateral` are hairline groups
  (a top rule, no box), so a panel never holds a box inside a box.
- **KPI strip.** One row of cards separated by 1 px `vdivider` rules. A value
  not yet produced reads "Not yet"; no benchmark reads "No reference".
- **Key chips.** `role="key"` shows a keyboard shortcut in mono type on a raised
  chip (Settings, Shortcuts).
- **Setting cards.** A Settings section is a `class="panel"` card: a `section`
  title, one `hint` line of purpose, then a two-column grid of label and control.
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
