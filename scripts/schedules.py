"""Generic schedule reader for architectural sheets (door / window / room finish schedules).

Text layer + table rulings only (no vision, no OCR):
  1. find schedule titles ("DOOR SCHEDULE (DETENTION)", "ROOM FINISH SCHEDULE", "WINDOW SCHEDULE ...")
  2. the first data row is the first line under the title that starts with a mark (A1021A, 100A, DA01, H1299)
  3. columns = the vertical rulings that cross that row; the table is the run of rulings around the title
  4. header text: every line between title and first row; a line belongs to every column its ruled cell spans,
     so group labels ("DOOR", "FRAME", "WALL") prefix the columns under them
  5. rows: a new row starts where the first column holds a mark; other lines continue the current row;
     the table ends where its rulings stop, at another schedule title, or after a large gap
All coordinates are displayed (rotation-applied) page coordinates.
"""
import re

import pymupdf

from pdfwords import rows as cluster_rows
from pdfwords import drawings, tdict, words

TITLE_RE = re.compile(r"^((ROOM\s+)?FINISH|DOOR|WINDOW|STOREFRONT)\s+SCHEDULE\b", re.I)
MARK_RE = re.compile(r"^[A-Z]{0,3}-?\d{1,5}[A-Z]?$")


def lines(page):
    m = page.rotation_matrix
    out = []
    for b in tdict(page)["blocks"]:
        for l in b.get("lines", []):
            t = " ".join("".join(s["text"] for s in l["spans"]).split())
            if t:
                r = pymupdf.Rect(l["bbox"]) * m
                out.append((r.x0, r.y0, r.x1, r.y1, t))
    return out


def vertical_text(page):
    """Boxes of vertical text lines (rotated column headers), displayed coordinates."""
    m = page.rotation_matrix
    out = []
    for b in tdict(page)["blocks"]:
        for l in b.get("lines", []):
            r = pymupdf.Rect(l["bbox"]) * m
            if r.height > r.width * 1.5 and r.width < 30:
                out.append((r.x0, r.y0, r.x1, r.y1))
    return out


def hrules(page):
    """Horizontal rule segments (y, x0, x1) in displayed coordinates."""
    m = page.rotation_matrix
    out = []
    for dr in drawings(page):
        for it in dr["items"]:
            if it[0] == "l":
                a, b = it[1] * m, it[2] * m
                if abs(a.y - b.y) < 0.6 and abs(a.x - b.x) > 6:
                    out.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x)))
            elif it[0] == "re":
                r = pymupdf.Rect(it[1]) * m
                if r.height < 1.5 and r.width > 6:
                    out.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                elif r.width > 6 and r.height > 6:
                    out += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
    return out


def rulings(page):
    """Vertical rule segments (x, y0, y1) in displayed coordinates."""
    m = page.rotation_matrix
    out = []
    for dr in drawings(page):
        for it in dr["items"]:
            if it[0] == "l":
                a, b = it[1] * m, it[2] * m
                if abs(a.x - b.x) < 0.6 and abs(a.y - b.y) > 6:
                    out.append(((a.x + b.x) / 2, min(a.y, b.y), max(a.y, b.y)))
            elif it[0] == "re":
                r = pymupdf.Rect(it[1]) * m
                if r.width < 1.5 and r.height > 6:
                    out.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif r.width > 6 and r.height > 6:  # boxed cells: both sides count
                    out += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    return out


def crossing(rules, y, x_lo=-1e9, x_hi=1e9):
    xs = sorted(x for x, y0, y1 in rules if y0 - 0.5 <= y <= y1 + 0.5 and x_lo <= x <= x_hi)
    out = []
    for x in xs:  # merge double lines
        if not out or x - out[-1] > 4:
            out.append(x)
    return out


def run_around(xs, cx, max_gap):
    """Contiguous run of x positions (gaps < max_gap) that contains / is nearest to cx."""
    if not xs:
        return []
    runs, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] < max_gap:
            cur.append(x)
        else:
            runs.append(cur)
            cur = [x]
    runs.append(cur)
    def dist(r):
        return 0 if r[0] <= cx <= r[-1] else min(abs(cx - r[0]), abs(cx - r[-1]))
    return min(runs, key=dist)


def kind_of(title):
    t = title.upper()
    if "FINISH" in t:
        return "room"
    if t.startswith("DOOR"):
        return "door"
    return "window"


def clean(t):
    return re.sub(r"\s+", " ", t.upper().replace("DETAL", "DETAIL").replace("OPENINING", "OPENING")).strip(" .:")


def find_tables(page):
    L = lines(page)
    W, H = page.rect.width, page.rect.height
    # schedule titles are upper case; mixed-case ones are drawing view titles under a viewport
    titles = [l for l in L if TITLE_RE.match(l[4]) and (l[3] - l[1]) < 40 and l[4] == l[4].upper()]
    if not titles:
        return []  # skip the (slow) vector read on plan sheets
    R = rulings(page)
    HR = hrules(page)
    VT = vertical_text(page)
    ws_all = words(page)
    tables = []
    for t in titles:
        tc = (t[0] + t[2]) / 2
        sib = [(o[0] + o[2]) / 2 for o in titles if o is not t and abs(o[1] - t[1]) < 60]
        x_min = max([(c + tc) / 2 for c in sib if c < tc] or [0])
        x_max = min([(c + tc) / 2 for c in sib if c > tc] or [W])
        # first data row: a mark-like word below the title whose row is crossed by >= 5 rulings
        x_min -= 40  # titles are not always centred over their table
        s_lo, s_hi = max(x_min, tc - W * 0.3), min(x_max, tc + W * 0.3)  # where the first row may start
        below = sorted((w for w in ws_all if t[3] < w[1] < t[3] + 320 and s_lo < w[0] < s_hi
                        and not any(v[0] - 1 <= w[0] and w[2] <= v[2] + 1 and v[1] - 1 <= w[1] and w[3] <= v[3] + 1 for v in VT)
                        and MARK_RE.match(w[4]) and re.search(r"\d", w[4])
                        and (w[2] - w[0]) >= (w[3] - w[1]) * 0.8), key=lambda w: (w[1], w[0]))  # not vertical header text
        start = None
        for w in below:
            yc = (w[1] + w[3]) / 2
            cr = [x for x in crossing(R, yc) if x_min - 2 <= x <= x_max + 2]
            lefts = [x for x in cr if x <= w[0] + 1]
            if not lefts or w[0] - lefts[-1] > 60:
                continue
            cols = [lefts[-1]]
            for x in cr:  # extend right from the key cell's left border while the grid continues
                if x > cols[-1] and x - cols[-1] < 450:
                    cols.append(x)
                elif x > cols[-1]:
                    break
            # right edge = end of the horizontal row rules that start at the key cell's left border
            segs = sorted((x0, x1) for y, x0, x1 in HR if w[1] - 8 <= y <= w[3] + 8)
            end = None
            for x0, x1 in segs:  # row rules are often drawn cell by cell: chain them from the left border
                if end is None and x0 <= cols[0] + 4 and x1 > cols[0] + 4:
                    end = x1
                elif end is not None and x0 <= end + 10:
                    end = max(end, x1)
            if end:
                cols = [x for x in cols if x <= end + 2]
            if len(cols) >= 5:
                start, xs = w, cols
                break
        if not start:
            continue
        y_data = start[1] - 1.5
        cols = list(zip(xs, xs[1:]))
        # header lines between title and first row, inside the table
        hdr = [l for l in L if t[3] - 1 < l[1] and l[3] < y_data + 1 and xs[0] - 2 < (l[0] + l[2]) / 2 < xs[-1] + 2]
        names = []
        for a, b in cols:
            parts = []
            for l in sorted(hdr, key=lambda l: (l[1], l[0])):
                lc, ly = (l[0] + l[2]) / 2, (l[1] + l[3]) / 2
                cx = crossing(R, ly, xs[0] - 2, xs[-1] + 2)
                lo = max([x for x in cx if x <= lc + 0.5] or [xs[0]])
                hi = min([x for x in cx if x >= lc - 0.5] or [xs[-1]])
                if lo <= xs[0] + 2 and hi >= xs[-1] - 2:
                    continue  # full-width section label ("Not Placed", "FIRST FLOOR"), not a header
                if lo - 1 <= (a + b) / 2 <= hi + 1:
                    parts.append(l[4])
            toks = clean(" ".join(parts)).split()
            toks = [k for i, k in enumerate(toks) if i == 0 or k != toks[i - 1]]  # "FRAME FRAME WIDTH"
            names.append(" ".join(toks) or f"COL{len(names) + 1}")
        seen = {}
        for i, n in enumerate(names):
            seen[n] = seen.get(n, 0) + 1
            if seen[n] > 1:
                names[i] = f"{n} ({seen[n]})"
        tables.append({"title": t[4], "kind": kind_of(t[4]), "names": names, "xs": xs, "top": y_data,
                       "title_box": t[:4], "page": page.number})
    for tb in tables:
        tb["rows"] = read_rows(page, tb, tables, R)
        if tb["rows"]:
            tb["bbox"] = (tb["xs"][0], tb["title_box"][1], tb["xs"][-1], tb["rows"][-1]["y1"])
    return [tb for tb in tables if tb["rows"]]


def read_rows(page, tb, all_tables, R):
    xs = tb["xs"]
    stop = page.rect.height
    for o in all_tables:
        if o is not tb and o["title_box"][1] > tb["top"] and o["xs"][0] < xs[-1] and o["xs"][-1] > xs[0]:
            stop = min(stop, o["title_box"][1])
    ws = words(page, (xs[0] - 1, tb["top"], xs[-1] + 1, stop))
    out, cur, last_y, misses = [], None, None, 0
    for r in cluster_rows(ws, 2.5):
        y = (r[0][1] + r[0][3]) / 2
        if len(crossing(R, y, xs[0] - 2, xs[-1] + 2)) < max(3, len(xs) // 2):
            misses += 1  # full-width section row ("SECOND FLOOR") or the table has ended
            if out and misses >= 3:
                break
            continue
        misses = 0
        cells = [[] for _ in range(len(xs) - 1)]
        for w in r:
            cx = (w[0] + w[2]) / 2
            for i in range(len(xs) - 1):
                if xs[i] <= cx < xs[i + 1]:
                    cells[i].append(w[4])
                    break
        first = cells[0]
        if last_y is not None and y - last_y > 60:
            break
        if first and MARK_RE.match(first[0]) and re.search(r"\d", first[0]):
            cur = {"key": first[0].rstrip(":"), "cells": [" ".join(c) for c in cells], "y": r[0][1], "y1": r[0][3]}
            out.append(cur)
            last_y = y
        elif cur is not None and any(cells):
            cur["cells"] = [(a + " " + " ".join(c)).strip() for a, c in zip(cur["cells"], cells)]
            cur["y1"] = max(w[3] for w in r)
            last_y = y
    # drop stray rows whose key shape differs from the table's (sheet border numbers, note numbers)
    lead = [r["key"][0].isalpha() for r in out]
    if lead and sum(lead) > len(lead) / 2:
        out = [r for r in out if r["key"][0].isalpha()]
    res = []
    for r in out:
        data = {}
        for n, v in zip(tb["names"], r["cells"]):
            v = v.replace(" - ", "-").strip()
            if n.startswith("COL") and not v or n.startswith(tb["names"][0] + " (") and v == r["key"]:
                continue
            if n == tb["names"][0]:
                v = v[len(r["key"]):].strip(" :") if v.startswith(r["key"]) else v
                if not v:
                    continue
                n = "NOTE"
            data[n] = v
        res.append({"key": r["key"], "data": data, "y": r["y"], "y1": r["y1"]})
    return res
