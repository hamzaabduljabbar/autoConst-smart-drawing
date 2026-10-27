---
name: smart-drawing
description: Turn an architectural PDF drawing set into a smart drawing - one offline HTML file where every door, room, window and wall-type tag on the plans is clickable and shows its schedule row, finish codes are decoded from the legends, detail bubbles jump to their sheet, and a search bar lights up every instance of a tag. Reads the PDF text layer and table rulings (no vision), adapts to each firm's own schedule columns. Use when someone wants to make a drawing set easier to read, cross-reference door/room/finish schedules with plans, build a clickable drawing viewer or dashboard, or check what a tag on a plan means.
---

# Smart drawing (architectural)

```
python scripts/smart_drawing.py <set.pdf> --out outputs/<p> [--project "Office building"] [--pages 100-221]
```

Writes `outputs/<p>/index.db` (SQLite) and `outputs/<p>/smart-drawing.html` (one file, opens offline).

## Steps

1. **Check the PDF has text.** Open a plan page with PyMuPDF; if `page.get_text()` is empty the set is scanned - stop and say so. This skill does not OCR.
2. **Scope the pages.** A combined set (arch + MEP + structural) indexes faster with `--pages` set to the architectural range. Find it from the sheet numbers (A-xxx) first. Large sets take ~10-25 min to index; tell the user.
3. **Run** `smart_drawing.py`. It prints counts per kind and HIGH counts (HIGH = schedule row AND tag found on a plan).
4. **Report honestly** from the printed summary: items per kind, how many are HIGH, and anything at 0 (e.g. no window schedule found). Never claim a kind the index did not find.
5. **Spot-check 3 items** in the DB against the PDF (one door, one room, one wall type): the row values must match the schedule exactly.
6. Hand over `smart-drawing.html`. It is self-contained: email it, put it on a drive, double-click to open.

## Options (scripts/export_viewer.py on an existing DB)

| flag | use |
|---|---|
| `--sheets A-101,A-102` | choose sheets (default: every sheet with tags or schedule rows) |
| `--dpi 80` | smaller file for big sets (each sheet ~0.5-1.5 MB at 100 dpi) |
| `--redact NAME,CITY` | blank these words on images and in data (sharing a client set) |
| `--mask-right 0.92` / `--mask-left 0.045` | blank the title-block strip / plot-stamp margin |
| `--files` | also write index.html + data.js + sheets/ (needs a web server) |

`refresh_meta.py set.pdf index.db` re-reads sheet titles and legends without a full rebuild.

## What it reads

- **Schedules** (door, room finish, window): found by title, columns from the table's ruling lines, headers from the cells above (group labels prefix columns). Works with vertical headers and side-by-side tables.
- **Wall types**: partition-type panels (tag `A3` = type A, suffix 3).
- **Legends / finish codes** (`LVT-1`, `P-3` ...) -> description.
- **Plan tags**: each schedule key on each plan sheet; door/room keys that collide are split by text size.
- **Callouts**: `2/A-510` style bubbles -> target sheet.

## Limits

- Vector (CAD-exported) PDFs only.
- Architectural only. Other trades need their own skill.
- Two-column legends can put a code under the wrong category; titles can need a manual fix (`UPDATE sheets SET title=...`).
