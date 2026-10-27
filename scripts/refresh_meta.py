#!/usr/bin/env python3
"""Re-run sheet titles and legend scoring on an existing index without the full (slow) rebuild.

Usage: py scripts/refresh_meta.py set.pdf arch.db
"""
import re
import sqlite3
import sys

import pymupdf

import build_index as B
import schedules


def main(pdf, db):
    doc = pymupdf.open(pdf)
    con = sqlite3.connect(db)
    pages = [r[0] for r in con.execute("select page from sheets where discipline like 'A%'")]
    best = {}
    for i in pages:
        p = doc[i]
        num = B.sheet_number(B.spans(p))
        con.execute("update sheets set title=? where page=?", (B.sheet_title(p, num), i))
        L = schedules.lines(p)
        if not any("LEGEND" in l[4].upper() or B.CODE_RE.match(l[4]) for l in L):
            continue
        tables = schedules.find_tables(p)
        for m in B.legends(p, [tb["bbox"] for tb in tables]):
            s = B.legend_score(m)
            if m["code"] not in best or s > best[m["code"]][0]:
                best[m["code"]] = (s, m, i)
    con.execute("delete from materials")
    for _, m, i in best.values():
        con.execute("insert into materials values(?,?,?,?)", (m["code"], m["category"], m["description"], i))
    con.commit()
    print(len(best), "materials")


if __name__ == "__main__":
    main(*sys.argv[1:])
