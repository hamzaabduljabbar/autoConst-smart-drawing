"""Words in displayed (rotation-applied) coordinates + row clustering."""
import pymupdf


def words(page, clip=None):
    """(x0, y0, x1, y1, text) in displayed coords; clip = (x0, y0, x1, y1) displayed."""
    m = page.rotation_matrix
    out = []
    for w in raw_words(page):
        r = pymupdf.Rect(w[:4]) * m
        if clip and not (r.x0 >= clip[0] and r.y0 >= clip[1] and r.x1 <= clip[2] and r.y1 <= clip[3]):
            continue
        out.append((r.x0, r.y0, r.x1, r.y1, w[4]))
    return out


def rows(ws, y_tol=3.0):
    ws = sorted(ws, key=lambda w: (w[1] + w[3]) / 2)
    out, cur, cy = [], [], None
    for w in ws:
        y = (w[1] + w[3]) / 2
        if cy is not None and abs(y - cy) > y_tol:
            out.append(sorted(cur, key=lambda w: w[0]))
            cur = []
        if not cur:
            cy = y
        cur.append(w)
    if cur:
        out.append(sorted(cur, key=lambda w: w[0]))
    return out


def size(page):
    return page.rect.width, page.rect.height  # page.rect is already the displayed (rotated) size


# ---- per-page cache: get_text("dict") and get_drawings() are slow on dense CAD sheets ----
_cache = {}


def _cached(page, what, fn):
    key = (id(page.parent), page.number)
    if key not in _cache:
        if len(_cache) > 2:
            _cache.pop(next(iter(_cache)))
        _cache[key] = {}
    c = _cache[key]
    if what not in c:
        c[what] = fn()
    return c[what]


def tdict(page):
    return _cached(page, "dict", lambda: page.get_text("dict"))


def raw_words(page):
    return _cached(page, "words", lambda: page.get_text("words"))


def drawings(page):
    return _cached(page, "drawings", lambda: page.get_drawings())
