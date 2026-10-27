#!/usr/bin/env python3
"""Export the index DB + sheet images for the HTML viewer.

Usage: py scripts/export_viewer.py set.pdf arch.db out_dir [--sheets A-001,A-101A,...] [--dpi 100]
       [--project "Office building"] [--redact NAME1,NAME2] [--mask-right 0.92] [--mask-left 0.045]

Writes out_dir/smart-drawing.html: ONE file (sheet images + index inside it), opens offline with a double-click.
--sheets  default = every sheet with tags or schedule rows on it
--files   also write out_dir/index.html + data.js + sheets/*.jpg (smaller, needs a web server)
--redact  words (case-insensitive) blanked on the images and dropped from text values
--mask-right  blank the title-block strip right of this fraction of the sheet width (firm, seal, project)
--mask-left   blank the left margin up to this fraction (plot stamps carry the file path)
"""
import argparse
import base64
import json
import os
import re
import sqlite3

import pymupdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("db")
    ap.add_argument("out")
    ap.add_argument("--sheets", default="")
    ap.add_argument("--files", action="store_true")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--project", default="")
    ap.add_argument("--redact", default="")
    ap.add_argument("--mask-right", type=float, default=0)
    ap.add_argument("--mask-left", type=float, default=0, help="blank the left margin (plot file path)")
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    doc = pymupdf.open(a.pdf)
    os.makedirs(os.path.join(a.out, "sheets") if a.files else a.out, exist_ok=True)
    redact = [r.strip().upper() for r in a.redact.split(",") if r.strip()]
    bad = re.compile("|".join(map(re.escape, redact)), re.I) if redact else None

    by_num = {r["number"]: dict(r) for r in con.execute("select * from sheets")}
    if a.sheets:
        want = [s.strip() for s in a.sheets.split(",")]
    else:  # sheets that carry something clickable
        used = {r[0] for r in con.execute("select page from tags union select page from items")}
        want = sorted(n for n, r in by_num.items() if n and r["page"] in used)
    sheets = [by_num[n] for n in want if n in by_num]
    pages = {s["page"] for s in sheets}

    for s in sheets:
        page = doc[s["page"]]
        W, H = page.rect.width, page.rect.height
        boxes = []
        if a.mask_right:
            boxes.append(pymupdf.Rect(W * a.mask_right, 0, W, H))
        if a.mask_left:
            boxes.append(pymupdf.Rect(0, 0, W * a.mask_left, H))
        if bad:
            m = page.rotation_matrix
            for w in page.get_text("words"):
                if bad.search(w[4]):
                    boxes.append((pymupdf.Rect(w[:4]) * m) + (-3, -3, 3, 3))
        pix = page.get_pixmap(dpi=a.dpi)
        sx, sy = pix.width / W, pix.height / H
        for b in boxes:  # paint over in pixel space (displayed orientation)
            r = pymupdf.IRect(int(b.x0 * sx), int(b.y0 * sy), int(b.x1 * sx) + 1, int(b.y1 * sy) + 1) & pix.irect
            if not r.is_empty:
                pix.set_rect(r, (255, 255, 255))
        s["px"] = [pix.width, pix.height]
        jpg = pix.tobytes("jpg", jpg_quality=80)
        s["img"] = f"sheets/{s['number']}.jpg"
        if a.files:
            with open(os.path.join(a.out, s["img"]), "wb") as f:
                f.write(jpg)
        s["data"] = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()

    def clean(v):
        return bad.sub("", v).strip() if bad and isinstance(v, str) else v

    items = []
    for r in con.execute("select * from items"):
        d = {k: clean(v) for k, v in json.loads(r["data"]).items()}
        items.append({"kind": r["kind"], "key": r["key"], "name": clean(r["name"]), "page": r["page"],
                      "source": r["source"], "confidence": r["confidence"], "data": d})
    data = {
        "project": a.project,
        "sheets": sheets,
        "items": items,
        "materials": [{k: clean(v) for k, v in dict(r).items()} for r in con.execute("select * from materials")],
        "tags": [dict(r) for r in con.execute("select * from tags") if r["page"] in pages],
        "callouts": [dict(r) for r in con.execute("select * from callouts") if r["page"] in pages],
        "all_sheets": [{"page": r["page"], "number": r["number"], "title": clean(r["title"])}
                       for r in con.execute("select page, number, title from sheets")],
    }
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer_template.html"), encoding="utf-8").read()
    js = "window.ARCH = " + json.dumps(data, separators=(",", ":")).replace("</", "<\\/") + ";"
    single = os.path.join(a.out, "smart-drawing.html")
    with open(single, "w", encoding="utf-8") as f:  # images inline: opens from a double-click
        f.write(tpl.replace('<script src="data.js"></script>', "<script>" + js + "</script>"))
    if a.files:
        for s in sheets:
            s.pop("data")
        with open(os.path.join(a.out, "data.js"), "w", encoding="utf-8") as f:
            f.write("window.ARCH = " + json.dumps(data, separators=(",", ":")) + ";\n")
        with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
            f.write(tpl)
    print({k: len(v) for k, v in data.items() if isinstance(v, list)},
          f"{single} {os.path.getsize(single) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
