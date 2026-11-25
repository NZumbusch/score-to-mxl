#!/usr/bin/env python3
"""Notehead finder + pitch labeller: an aid for manual transcription (not a full OMR).

    python3 tools/heads.py PAGE.png FIRST LAST CLEFS [NPARTS] --out DIR [--zoom 1.3]

CLEFS: one spec per staff, comma separated.  A spec is a clef name optionally
followed by clef changes at page x-positions:  "bass"  or  "bass>treble@1500>bass@2300".
Use "-" to skip a staff.

What it does: removes staff lines, finds filled (and, with hole-filling, hollow)
notehead blobs, splits vertically stacked blobs (chords / seconds), converts
the vertical centre to a diatonic position relative to the nearest staff and
draws the pitch name (without accidental -- read accidentals yourself) in red
next to each head.  Ledger-line positions are drawn as faint blue dashes.

Limitations (see docs/FINDINGS.md): beams can be mistaken for heads, hollow
heads crossed by ledger lines are sometimes missed, x-heads/diamonds are not
detected, grace notes are smaller and may be missed.  ALWAYS check visually.
"""
import sys, os, argparse
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from split_pages import find_staves

NAMES = 'CDEFGAB'
BASE = {'treble': 4 * 7 + 2, 'bass': 2 * 7 + 4, 'alto': 3 * 7 + 3, 'tenor': 3 * 7 + 1}


def parse_clef(spec):
    segs = []
    for i, p in enumerate(spec.split('>')):
        if '@' in p:
            c, x = p.split('@')
            segs.append((int(x), c))
        else:
            segs.append((0 if i == 0 else 0, p))
    return segs


def clef_at(segs, x):
    c = segs[0][1]
    for x0, cl in segs:
        if x >= x0:
            c = cl
    return c


def detect(arr, sp):
    """Return list of (cx, cy, w, h) head candidates in page coords."""
    ink = (arr < 150).astype(np.uint8)
    # remove staff lines: horizontal runs longer than 3 spaces, thin
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(3 * sp), 1)))
    thin = ink.copy()
    # only remove pixels where vertical thickness is small (staff/ledger lines), keep heads
    vert_thick = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(0.3 * sp)))))
    thin[(horiz > 0) & (vert_thick == 0)] = 0
    # fill hollow heads
    filled = thin.copy()
    cnts, hier = cv2.findContours(thin, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is not None:
        for i, c in enumerate(cnts):
            if hier[0][i][3] >= 0:  # hole
                x, y, w, h = cv2.boundingRect(c)
                if 0.25 * sp < w < 1.6 * sp and 0.2 * sp < h < 1.1 * sp:
                    cv2.drawContours(filled, [c], -1, 1, -1)
    # opening with an ellipse a bit smaller than a head removes stems, beams' thin parts, text strokes
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(0.75 * sp)), max(3, int(0.6 * sp))))
    blobs = cv2.morphologyEx(filled, cv2.MORPH_OPEN, k)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(blobs)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < 0.8 * sp or w > 2.2 * sp or h < 0.55 * sp:
            continue
        # beams: wide and flat or very long
        if w > 1.9 * sp and h < 0.9 * sp:
            continue
        if h > 1.3 * sp:
            # stacked heads (chord): split the blob at narrow "waists" of its row-width profile
            sub = (lab[y:y + h, x:x + w] == i)
            prof = sub.sum(1).astype(float)
            prof = np.convolve(prof, np.ones(3) / 3, mode='same')
            cuts = [0]
            for r in range(int(0.35 * sp), h - int(0.35 * sp)):
                if prof[r] < 0.72 * prof.max() and prof[r] <= prof[r - 1] and prof[r] <= prof[r + 1] \
                        and r - cuts[-1] > 0.45 * sp:
                    cuts.append(r)
            cuts.append(h)
            for c0, c1 in zip(cuts, cuts[1:]):
                seg = c1 - c0
                k = max(1, int(round(seg / (0.95 * sp))))  # unseparated adjacent heads
                for j in range(k):
                    cy = y + c0 + (j + 0.5) * seg / k
                    xs = np.where(sub[int(cy - y)])[0]
                    cx = x + (xs.mean() if len(xs) else w / 2)
                    out.append((cx, cy, w, seg / k, 'chord' if k == 1 else 'chord?'))
            continue
        out.append((x + w / 2, y + h / 2, w, h, 'head'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('page'); ap.add_argument('first', type=int); ap.add_argument('last', type=int)
    ap.add_argument('clefs'); ap.add_argument('nparts', type=int, nargs='?', default=3)
    ap.add_argument('--out', default='/tmp'); ap.add_argument('--zoom', type=float, default=1.3)
    ap.add_argument('--pad', type=float, default=6.0)
    ap.add_argument('--x0', type=float, default=0.0); ap.add_argument('--x1', type=float, default=1.0)
    a = ap.parse_args()
    arr = np.array(Image.open(a.page).convert('L'))
    st = find_staves(arr)
    sp = float(np.median([s[2] for s in st]))
    clefs = [parse_clef(c) for c in a.clefs.split(',')]
    top = max(0, int(st[a.first - 1][0] - a.pad * sp))
    bot = min(arr.shape[0], int(st[a.last - 1][1] + a.pad * sp))
    heads = detect(arr[top:bot], sp)
    rgb = Image.fromarray(arr[top:bot]).convert('RGB')
    dr = ImageDraw.Draw(rgb)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 14)
    except Exception:
        font = ImageFont.load_default()
    staves = list(range(a.first, a.last + 1))

    def pitch_of(xp, yabs):
        # nearest staff among the selected ones, limited to midpoints
        best = None
        for si, cl in zip(staves, clefs):
            t, b, _ = st[si - 1]
            d = 0 if t <= yabs <= b else min(abs(yabs - t), abs(yabs - b))
            if best is None or d < best[0]:
                best = (d, si, cl)
        _, si, cl = best
        c = clef_at(cl, xp)
        if c == '-':
            return None
        t, b, _ = st[si - 1]
        spc = (b - t) / 4
        k = int(round((b - yabs) / (spc / 2)))
        d = BASE[c] + k
        return NAMES[d % 7] + str(d // 7)

    # ledger guides
    for si, cl in zip(staves, clefs):
        t, b, _ = st[si - 1]
        spc = (b - t) / 4
        for k in list(range(1, 7)) + list(range(-6, 0)):
            y = (t - k * spc if k > 0 else b - k * spc) - top
            if 0 <= y < rgb.height:
                for x in range(0, rgb.width, 14):
                    dr.line([(x, y), (x + 4, y)], fill=(150, 190, 255), width=1)
    for cx, cy, w, h, kind in heads:
        if kind in ('chord', 'chord?'):
            p = pitch_of(cx, cy + top)
            if p:
                dr.text((cx + w / 2 + 1, cy - 8), p + ('?' if kind == 'chord?' else ''), fill=(200, 0, 200), font=font)
            continue
        if kind == 'stack':
            # label every half space inside the stack where ink is wide
            y = cy + 0.5 * sp
            labels = []
            while y < cy + h - 0.25 * sp:
                p = pitch_of(cx, y + top)
                if p:
                    labels.append(p)
                y += sp / 2
            dr.rectangle([cx - w / 2, cy, cx + w / 2, cy + h], outline=(255, 140, 0))
            dr.text((cx + w / 2 + 2, cy), '/'.join(labels[::-1]) + '?', fill=(255, 120, 0), font=font)
        else:
            p = pitch_of(cx, cy + top)
            if p:
                dr.text((cx + w / 2 + 1, cy - 8), p, fill=(220, 0, 0), font=font)
    # page-x ruler (for specifying clef-change positions)
    for x in range(0, rgb.width, 100):
        dr.line([(x, 0), (x, 10)], fill=(0, 120, 255), width=2)
        dr.text((x + 2, 0), str(x), fill=(0, 120, 255), font=font)
    # trim and split
    W = rgb.width
    cols = np.where((arr[top:bot] < 128).sum(0) > 2)[0]
    l, r = int(cols[0]), int(cols[-1])
    l, r = int(l + a.x0 * (r - l)), int(l + a.x1 * (r - l))
    n = a.nparts
    ov = int(0.04 * (r - l))
    base = os.path.splitext(os.path.basename(a.page))[0]
    for k in range(n):
        x0 = max(l, l + k * (r - l) // n - ov); x1 = min(r, l + (k + 1) * (r - l) // n + ov)
        im = rgb.crop((x0, 0, x1, rgb.height))
        if a.zoom != 1:
            im = im.resize((int(im.width * a.zoom), int(im.height * a.zoom)), Image.LANCZOS)
        fn = os.path.join(a.out, f'h_{base}_{a.first}-{a.last}_{k + 1}.png')
        im.save(fn)
        print(fn, f'x={x0}-{x1}')


if __name__ == '__main__':
    main()
