# Smart Drawing (Claude skill)

**Turn an architectural PDF drawing set into one clickable HTML file. Click a door, see its schedule.**

A door tag sits on the plan. Its size, frame and hardware are in the schedule three sheets away. Its finish is a code explained in a legend, and the wall it sits in is defined on yet another sheet. Reading one item means flipping between sheets.

This skill reads the set once and links it all together:

- **Doors:** click one and see its full schedule row (size, frame, glass, hardware, fire rating).
- **Rooms:** click one and see floor, base and wall finishes, with the codes decoded into products.
- **Wall tags:** click one and see how the wall is built (studs, width, fire and sound rating).
- **Detail bubbles:** click one to open that sheet.
- **Search:** type a tag and every instance lights up on the plan.
- **Whole-set counts and filters:** doors, rooms, windows, wall types, finishes.

The output is **one HTML file**. No install, no login, no upload. Double-click it and it works offline.

## Results

| Set | Sheets | Found | Linked on plans |
|---|---|---|---|
| Public safety facility (firm 1, 122 arch sheets) | 122 | 468 doors, 453 rooms, 12 window types, 10 wall types, 79 finish codes | 466 / 468 doors, 451 / 453 rooms |
| IndyGo Training Facility (firm 2, public bid set) | 15 | 26 doors, 24 rooms, 17 finish codes | 26 / 26 doors, 24 / 24 rooms |

The two firms lay out their schedules differently. Nothing was configured per set: the skill reads each schedule's own columns.

Try it: open `examples/indygo/smart-drawing.html`.

## Install

```
pip install -r requirements.txt
```

Copy this folder into `~/.claude/skills/smart-drawing/` (or your project's `.claude/skills/`), then ask Claude: *"make a smart drawing from inputs/my-set.pdf"*.

Or run it directly:

```
python scripts/smart_drawing.py my-set.pdf --out outputs/my-project --project "Office building"
```

## How it works

1. **Index:** `build_index.py` reads the PDF's text and table lines (no AI vision, no OCR) into SQLite: sheets, schedule rows, legend codes, wall types, plan tags and callouts. An item is HIGH when its schedule row and its tag on a plan are both found.
2. **Viewer:** `export_viewer.py` renders the sheets and writes the index and images into one HTML file.

Every value you see when you click comes from the drawing's own text.

## Limits

- Needs a CAD-exported PDF. Scanned sets won't work.
- Architectural only for now.
- A big set takes 10-25 minutes to index the first time.
- Windows listed only as elevation types (no window schedule) are not picked up on every set (IndyGo: 0).
- Two-column legends can put a code under the wrong category.

Source-available licence (see LICENSE). Part of the AutoConst tools by [Hamza Jabbar](https://hamzajabbar.online).
