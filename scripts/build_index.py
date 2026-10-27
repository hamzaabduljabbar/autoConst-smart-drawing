#!/usr/bin/env python3
"""Index an architectural drawing set into SQLite (any firm's layout, text layer + rulings only).

  sheets     page, sheet number (largest sheet-number text), title (title block, above the number)
  items      every schedule row: doors, rooms (finish schedule), windows; wall types from partition
             diagrams. Full row kept as JSON with the schedule's own column names.
  materials  legend codes (CPT-1, SG-2, P-1 ...) -> description, from legends / notes on schedule sheets
  tags       where each item's tag sits on every plan sheet (normalised 0-1 coords) -> the viewer
  callouts   detail / section bubbles (n over A-510, or n/A-510) -> target sheet + page

Confidence: HIGH = schedule row AND tag found on a plan; MEDIUM = only one of the two.

Usage: py scripts/build_index.py set.pdf out.db [--disc A] [--pages 100-221]
"""
import argparse
import json
import re
import sqlite3
from collections import Counter

import pymupdf

import schedules
from pdfwords import rows, tdict, words

SHEET_RE = re.compile(r"[A-Z]{1,2}-?\d{3}[A-Z]?")
CODE_RE = re.compile(r"^([A-Z]{1,4}-\d{1,2}[A-Z]?)\s+(.+)$")
ABBR_RE = re.compile(r"^([A-Z]{2,5})\s+-\s+([A-Z].+)$")
PART_TITLE = re.compile(r"^PARTITION TYPE ([A-Z])$")
SKIP_TITLE = {"ISSUE DATE", "SUBMITTAL", "PROJECT NO.", "DRAWING TITLE:", "SHEET NUMBER:", "CONSTRUCTION SET"}

SCHEMA = """
CREATE TABLE sheets(page INT PRIMARY KEY, number TEXT, title TEXT, discipline TEXT, w REAL, h REAL);
CREATE TABLE items(kind TEXT, key TEXT, name TEXT, page INT, source TEXT, data TEXT, confidence TEXT,
  PRIMARY KEY(kind, key));
CREATE TABLE materials(code TEXT PRIMARY KEY, category TEXT, description TEXT, page INT);
CREATE TABLE callouts(label TEXT, detail TEXT, target_sheet TEXT, target_page INT, page INT,
  x REAL, y REAL, w REAL, h REAL);
CREATE TABLE tags(kind TEXT, key TEXT, item TEXT, page INT, x REAL, y REAL, w REAL, h REAL);
"""


def norm(page, b):
    W, H = page.rect.width, page.rect.height
    return b[0] / W, b[1] / H, (b[2] - b[0]) / W, (b[3] - b[1]) / H


def spans(page):
    """(x0, y0, x1, y1, text, size) per span, displayed coordinates."""
    m = page.rotation_matrix
    out = []
    for b in tdict(page)["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s["text"].strip():
                    r = pymupdf.Rect(s["bbox"]) * m
                    out.append((r.x0, r.y0, r.x1, r.y1, s["text"].strip(), s["size"]))
    return out


def sheet_number(sp):
    best = None
    for s in sp:
        if SHEET_RE.fullmatch(s[4]) and (best is None or s[5] > best[5]):
            best = s
    return best


def sheet_title(page, num):
    if not num:
        return ""
    W = page.rect.width
    m = page.rotation_matrix
    blocks = []
    for b in page.get_text("blocks"):
        r = pymupdf.Rect(b[:4]) * m
        t = " ".join(b[4].split())
        if r.x0 > W * 0.85 and r.y1 <= num[1] + 2 and r.y0 > num[1] - 220 and t and t != num[4]:
            blocks.append((r.y1, t))
    out = []
    for _, t in sorted(blocks, reverse=True):  # walk up from the sheet number
        if t.upper() == "SHEET NUMBER:" and not out:
            continue
        if t.upper() in SKIP_TITLE or re.search(r"\d", t) or '"' in t:
            break  # dates, project numbers, dimension text from a neighbouring table
        if t.upper() in ("PLAN NORTH", "KEYPLAN"):
            continue  # key plan labels sit in the same strip
        out.insert(0, t)
    return " ".join(out)


def name_of(kind, data):
    keys = {"room": ("ROOM NAME", "NAME"), "door": ("TO ROOM", "DOOR ROOM", "ROOM")}.get(kind, ("COMMENTS", "ELEVATION"))
    for k in keys:
        for col, v in data.items():
            if (col == k or col.endswith(" " + k)) and v:
                return re.sub(r"^[A-Z]?\d{3,5}[A-Z]?:\s*", "", v)  # "A1021: VESTIBULE" -> "VESTIBULE"
    return ""


# ---------- legends ----------

def legends(page, skip_boxes=()):
    """Code lines (CPT-1 ..., SG-2 ..., AL - ALUMINUM) + the indented lines under them; the latest
    un-indented non-code line above a code in the same column is its category."""
    L = sorted(schedules.lines(page), key=lambda l: (l[1], l[0]))
    W = page.rect.width
    inside = lambda l: any(b[0] - 2 <= l[0] and l[2] <= b[2] + 2 and b[1] - 2 <= l[1] and l[3] <= b[3] + 2
                           for b in skip_boxes)
    L = [l for l in L if not inside(l)]  # schedule cells are not legend entries
    bare = re.compile(r"[A-Z]{1,4}-\d{1,2}[A-Z]?")
    codes, out_abbr = [], []  # abbreviations ("HM - HOLLOW METAL") are one line each
    for l in L:
        if l[0] > W * 0.92:
            continue
        m = CODE_RE.match(l[4])
        a = ABBR_RE.match(l[4])
        if m:
            codes.append((l, m.group(1), m.group(2)))
        elif a:
            out_abbr.append({"code": a.group(1), "category": "Abbreviation", "description": a.group(2)})
        elif bare.fullmatch(l[4]):
            beside = [b for b in L if abs(b[1] - l[1]) < 3 and l[2] < b[0] < l[2] + 150]
            codes.append((l, l[4], min(beside)[4] if beside else ""))
    out = []
    for i, (l, code, first) in enumerate(codes):
        nxt = [c[0][1] for c in codes[i + 1:] if abs(c[0][0] - l[0]) < 12 and c[0][1] > l[1]]
        y_end = min(nxt + [l[3] + 140])
        body = [b for b in L if l[1] + 2 < b[1] < y_end - 1 and l[0] + 8 < b[0] < l[0] + 320 and b[4] != first]
        heads = [b for b in L if abs(b[0] - l[0]) < 6 and b[1] < l[1] and not CODE_RE.match(b[4])
                 and not ABBR_RE.match(b[4]) and not bare.fullmatch(b[4]) and l[1] - b[1] < 900 and len(b[4]) < 50]
        cat = heads[-1][4].rstrip(":") if heads else ""
        desc = " | ".join([first] + [b[4] for b in body]) if first else " | ".join(b[4] for b in body)
        if desc.strip(" |"):
            out.append({"code": code, "category": cat, "description": desc.strip(" |")})
    return out + out_abbr


def legend_score(m):
    """Real legend entries carry product lines (MFG:, TYPE:, MANUFACTURER:) and a CSI heading like
    "(09 65 19) RESILIENT TILE FLOORING"; plan labels that reuse the code carry room names and dimensions."""
    d, c = m["description"], m["category"] or ""
    return (bool(re.search(r"\b(MFG|TYPE|MANUFACTURER|STYLE|COLOR):", d)), bool(re.match(r"\(\d\d \d\d", c)),
            not re.search(r"\d+' - \d|[A-Z]\d{4}", d), bool(re.search(r"[A-Z]{3}", c)), -abs(len(d) - 120))


# ---------- partition types ----------

def partitions(page):
    L = schedules.lines(page)
    H = page.rect.height
    titles = [(l, PART_TITLE.match(l[4]).group(1)) for l in L if PART_TITLE.match(l[4])]
    out = []
    for l, typ in titles:
        same_row = sorted(o[0][0] for o in titles if abs(o[0][1] - l[1]) < 6)
        right = min([x for x in same_row if x > l[0] + 10] or [l[0] + 300]) - 75
        left = l[0] - 75
        below = [o[0][1] for o in titles if o[0][1] > l[1] + 50 and o[0][0] < right and o[0][2] > left]
        bottom = min(below + [H * 0.985])
        rs = [" ".join(w[4] for w in r) for r in rows(words(page, (left, l[3], right, bottom)), 3)]

        def between(a, b):
            i = next((k for k, r in enumerate(rs) if r.startswith(a)), None)
            if i is None:
                return []
            j = next((k for k, r in enumerate(rs) if k > i and r.startswith(b)), len(rs))
            return rs[i + 1:j]

        desc = [r for r in between("SECTION", "PLAN")
                if not re.fullmatch(r"(DECK|CLG\.|FLR\.|[\d /\"'-]+|[A-Z]\d{1,2})", r) and "GRAPHICAL DEFAULT" not in r]
        default = next((r for r in rs if re.fullmatch(rf"{typ}\d{{1,2}}", r)), "")
        data = {"TYPE": f"Partition type {typ}", "GRAPHICAL DEFAULT": default, "DESCRIPTION": " ".join(desc)}
        for r in between("DESIGN CRITERIA", "CONSTRUCTION"):
            m = re.match(r"^(?:\d+\s+)?(IF [A-Z0-9 .\-]+?)\s+(\S+)\s+(\d+)\s+(\d+)$", r)
            if m:
                data[m.group(1)] = f"UL {m.group(2)} · STC {m.group(3)} · STC w/ SAB {m.group(4)}"
        for r in between("CONSTRUCTION", "~~"):
            m = re.match(r"^(\d{1,2})\s+(.+)$", r)
            if m:
                sizes = re.findall(r"\d+(?: \d/\d)?\"", m.group(2))
                data[f"SUFFIX {m.group(1)}"] = (f"{sizes[0]} studs · {sizes[1]} overall" if len(sizes) >= 2
                                                else m.group(2).capitalize())
        out.append({"key": typ, "data": data})
    return out


# ---------- callouts ----------

def callouts(page, sheet_pages):
    out = []
    ws = words(page)
    for w in ws:
        m = re.fullmatch(r"(\d{1,2})/([A-Z]{1,2}-?\d{3}[A-Z]?)", w[4])
        if m:
            out.append((m.group(1), m.group(2), w[:4]))
            continue
        if SHEET_RE.fullmatch(w[4]) and (w[3] - w[1]) < 14:
            cx, h = (w[0] + w[2]) / 2, w[3] - w[1]
            near = [v for v in ws if re.fullmatch(r"\d{1,2}", v[4]) and abs((v[3] - v[1]) - h) < 2
                    and abs((v[0] + v[2]) / 2 - cx) < 45 and abs((v[1] + v[3]) / 2 - (w[1] + w[3]) / 2) < 40]
            if near:
                v = min(near, key=lambda v: abs((v[0] + v[2]) / 2 - cx) + abs(v[1] - w[1]))
                out.append((v[4], w[4], (min(v[0], w[0]), min(v[1], w[1]), max(v[2], w[2]), max(v[3], w[3]))))
    return [(det, tgt, box, sheet_pages.get(tgt)) for det, tgt, box in out]


def fix_wall_room_clash(con):
    """Some sets name small rooms like partition tags (cell "A3" vs partition type A suffix 3). A room tag
    appears once or twice on a sheet; a partition tag repeats along walls. Re-file repeated ones as walls."""
    walls = {r[0] for r in con.execute("select key from items where kind='wall'")}
    rows = con.execute("""select page, key, count(*) from tags where kind='room' group by page, key
                          having count(*) > 2""").fetchall()
    moved = 0
    for page, key, n in rows:
        if re.fullmatch(r"[A-Z]\d{1,2}", key) and key[0] in walls:
            con.execute("update tags set kind='wall', item=? where kind='room' and page=? and key=?", (key[0], page, key))
            moved += n
    for kind, key in con.execute("select kind, key from items").fetchall():
        n = con.execute("select count(*) from tags where kind=? and item=?", (kind, key)).fetchone()[0]
        con.execute("update items set confidence=? where kind=? and key=?", ("HIGH" if n else "MEDIUM", kind, key))
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("db")
    ap.add_argument("--disc", default="A")
    ap.add_argument("--pages", help="page range to scan, 1-based, e.g. 100-221")
    a = ap.parse_args()

    doc = pymupdf.open(a.pdf)
    pages = range(doc.page_count)
    if a.pages:
        lo, hi = map(int, a.pages.split("-"))
        pages = range(lo - 1, min(hi, doc.page_count))
    con = sqlite3.connect(a.db)
    con.executescript("".join(f"DROP TABLE IF EXISTS {t};" for t in
                              ("sheets", "items", "materials", "callouts", "tags", "rooms", "doors",
                               "window_types")) + SCHEMA)

    sheet_pages, disc_pages, sp_cache = {}, [], {}
    for i in pages:
        p = doc[i]
        sp = spans(p)
        sp_cache[i] = sp
        num = sheet_number(sp)
        n = num[4] if num else None
        d = re.match(r"[A-Z]+", n).group(0) if n else "?"
        sheet_pages[n] = i
        con.execute("INSERT INTO sheets VALUES(?,?,?,?,?,?)", (i, n, sheet_title(p, num), d, p.rect.width, p.rect.height))
        if d.startswith(a.disc):
            disc_pages.append(i)

    # schedules, legends, partition types
    items, sched_pages, best = {}, {"door": set(), "room": set(), "window": set()}, {}
    for i in disc_pages:
        p = doc[i]
        tables = schedules.find_tables(p)
        for tb in tables:
            sched_pages[tb["kind"]].add(i)
            for r in tb["rows"]:
                items.setdefault((tb["kind"], r["key"]), {
                    "page": i, "source": tb["title"].title(), "data": r["data"], "name": name_of(tb["kind"], r["data"])})
        if tables or any("LEGEND" in l[4].upper() for l in schedules.lines(p)):
            for m in legends(p, [tb["bbox"] for tb in tables]):
                # the same code also appears as a plain label on plans; keep the real legend entry
                score = legend_score(m)
                if m["code"] not in best or score > best[m["code"]][0]:
                    best[m["code"]] = (score, m, i)
        for pt in partitions(p):
            items.setdefault(("wall", pt["key"]), {"page": i, "source": "Partition Diagrams", "data": pt["data"],
                                                   "name": pt["data"]["TYPE"]})
    for _, m, i in best.values():
        con.execute("INSERT INTO materials VALUES(?,?,?,?)", (m["code"], m["category"], m["description"], i))

    walls = {k for kind, k in items if kind == "wall"}
    lookup = {}
    for kind, key in items:
        if kind != "wall":
            lookup.setdefault(key, set()).add(kind)
    all_sched = set().union(*sched_pages.values())

    # plan tags: plan sheets only (schedule sheets list every key in their tables)
    found = Counter()
    for i in disc_pages:
        if i in all_sched:
            continue
        p = doc[i]
        W = p.rect.width
        # a number can be both a room (F1161) and that room's door (F1161): door and room tags use
        # different text sizes on a sheet, so learn each size from the unambiguous tags
        size_of = {}
        for k in ("door", "room"):
            sz = [round(s[5], 1) for s in sp_cache[i] if lookup.get(s[4].rstrip(":")) == {k}]
            if sz:
                size_of[k] = Counter(sz).most_common(1)[0][0]
        for s in sp_cache[i]:
            if s[0] > W * 0.9:
                continue  # title block
            t = s[4].rstrip(":")
            kinds, item, kind = lookup.get(t, set()), t, None
            if len(kinds) == 1:
                kind = next(iter(kinds))
            elif kinds:
                cand = [k for k in kinds if k in size_of]
                kind = min(cand, key=lambda k: abs(size_of[k] - s[5])) if cand else sorted(kinds)[-1]
            elif re.fullmatch(r"[A-Z]\d{1,2}", t) and t[0] in walls and s[5] < 12:
                kind, item = "wall", t[0]  # A3 = partition type A, suffix 3 (grid bubbles use bigger text)
            if kind is None:
                continue
            con.execute("INSERT INTO tags VALUES(?,?,?,?,?,?,?,?)", (kind, t, item, i, *norm(p, s[:4])))
            found[(kind, item)] += 1
        for det, tgt, box, tpage in callouts(p, sheet_pages):
            if box[0] <= W * 0.9:
                con.execute("INSERT INTO callouts VALUES(?,?,?,?,?,?,?,?,?)", (f"{det}/{tgt}", det, tgt, tpage, i, *norm(p, box)))

    for (kind, key), it in items.items():
        conf = "HIGH" if found[(kind, key)] else "MEDIUM"
        con.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)",
                    (kind, key, it["name"], it["page"], it["source"], json.dumps(it["data"]), conf))
    fix_wall_room_clash(con)
    con.commit()

    q = lambda s: con.execute(s).fetchall()
    print(json.dumps({
        "sheets": q("select count(*) from sheets")[0][0],
        "items": dict(q("select kind, count(*) from items group by kind")),
        "items_HIGH": dict(q("select kind, count(*) from items where confidence='HIGH' group by kind")),
        "materials": q("select count(*) from materials")[0][0],
        "tags": dict(q("select kind, count(*) from tags group by kind")),
        "callouts": q("select count(*) from callouts")[0][0],
        "callouts_in_set": q("select count(*) from callouts where target_page is not null")[0][0],
    }, indent=1))


if __name__ == "__main__":
    main()
