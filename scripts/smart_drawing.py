#!/usr/bin/env python3
"""One command: architectural PDF set -> index DB -> one offline HTML smart drawing.

Usage: py scripts/smart_drawing.py set.pdf --out outputs/<project> [--project "Office building"]
       [--pages 100-221] [--disc A] [--dpi 100]

Writes outputs/<project>/index.db and outputs/<project>/smart-drawing.html.
Extra export options (--sheets, --redact, --mask-right ...): run export_viewer.py on the DB directly.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--project", default="")
    ap.add_argument("--pages")
    ap.add_argument("--disc", default="A")
    ap.add_argument("--dpi", default="100")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    db = os.path.join(a.out, "index.db")
    idx = [sys.executable, os.path.join(HERE, "build_index.py"), a.pdf, db, "--disc", a.disc]
    if a.pages:
        idx += ["--pages", a.pages]
    subprocess.run(idx, check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "export_viewer.py"), a.pdf, db, a.out,
                    "--project", a.project, "--dpi", a.dpi], check=True)


if __name__ == "__main__":
    main()
