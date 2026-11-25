#!/usr/bin/env python3
"""Rasterise a scanned score PDF, rotate/deskew pages, and cut them into systems.

Usage:
    python3 tools/split_pages.py SCORE.pdf OUTDIR [--rotate 90] [--dpi 300]

Writes OUTDIR/pNN.png (upright full page) and OUTDIR/pNN_sK.png (one system each,
with a little margin) plus OUTDIR/pNN_sK_partM.png (left/right halves at
higher zoom, handy for reading dense passages).

The system finder works on the horizontal projection profile: staff lines are
rows with many dark pixels; staves are clusters of 5 lines; systems are runs of
staves separated by a gap that is clearly larger than the in-system gaps.
"""
import argparse, os, subprocess, sys, glob
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def deskew(arr):
    """Find small rotation angle maximising the sharpness of the row profile."""
    import cv2
    best = (0, -1)
    h, w = arr.shape
    small = cv2.resize(arr, (w // 3, h // 3))
    inv = 255 - small
    for ang in np.arange(-1.5, 1.51, 0.1):
        M = cv2.getRotationMatrix2D((small.shape[1] / 2, small.shape[0] / 2), ang, 1)
        r = cv2.warpAffine(inv, M, (small.shape[1], small.shape[0]))
        prof = r.sum(1).astype(float)
        score = (prof ** 2).sum()
        if score > best[1]:
            best = (ang, score)
    ang = best[0]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1)
    return cv2.warpAffine(arr, M, (w, h), borderValue=255), ang


def find_staves_strip(arr, xa, xb):
    h, w = arr.shape
    # use a strip near the left edge of the systems: robust against page curvature / skew
    dark = arr[:, xa:xb] < 128
    prof = dark.sum(1)
    rows = np.where(prof > 0.45 * dark.shape[1])[0]
    # merge adjacent rows into lines
    lines = []
    for r in rows:
        if lines and r - lines[-1][-1] <= 5:
            lines[-1].append(r)
        else:
            lines.append([r])
    lines = [int(np.mean(l)) for l in lines]
    # group into staves of 5 with equal spacing; tolerate spurious lines (slurs, beams) in between
    gaps = np.diff(lines)
    cand = gaps[(gaps > 12) & (gaps < 40)]
    d0 = float(np.median(cand)) if len(cand) else 21.0
    staves = []
    used = set()
    for i, y0 in enumerate(lines):
        if False:
            continue
        picked = [i]
        d = None
        for k in range(1, 5):
            prev = lines[picked[-1]]
            nxt = [j for j in range(len(lines)) if 0.8 * d0 <= lines[j] - prev <= 1.25 * d0]
            if d is not None:
                nxt = [j for j in nxt if abs(lines[j] - prev - d) <= 0.15 * d0]
            if not nxt:
                break
            j = min(nxt, key=lambda j: abs(lines[j] - prev - (d or d0)))
            if d is None:
                d = lines[j] - prev
            picked.append(j)
        if len(picked) == 5:
            ys = [lines[j] for j in picked]
            staves.append((ys[0], ys[-1], float(np.mean(np.diff(ys)))))
            pass
    return staves


def find_staves(arr):
    """Union of staves found in several vertical strips (robust to slurs, indents, curvature)."""
    h, w = arr.shape
    colsum = (arr < 128).sum(0)
    xs = np.where(colsum > 0.05 * h)[0]
    x0 = int(xs[0]) if len(xs) else 0
    cands = []
    for xa in (x0 + 60, int(w * 0.3), int(w * 0.5), int(w * 0.7)):
        cands.extend(find_staves_strip(arr, xa, xa + w // 6))
    dark = arr < 128
    xs0 = x0 + 40
    def score(stf):
        t, b, d = stf
        ys = [int(round(t + k * (b - t) / 4)) for k in range(5)]
        return sum(dark[y - 1:y + 2, xs0:w - 40].any(0).mean() for y in ys)
    # among overlapping candidates keep the one whose 5 lines are darkest across the page width
    cands.sort(key=lambda c: -score(c))
    found = []
    for c in cands:
        if all(abs(c[0] - f[0]) > 3 * c[2] for f in found) and score(c) > 2.5:
            found.append(c)
    return sorted(found)


def staff_left(arr, st):
    """x of the left end of the staff lines."""
    band = arr[st[0]:st[1] + 1] < 128
    cols = np.where(band.sum(0) >= 4)[0]
    return int(cols[0]) if len(cols) else 0


def connected(arr, a, b):
    """True if a vertical line joins staff a to staff b near their left edge (system barline/brace)."""
    x0 = min(staff_left(arr, a), staff_left(arr, b))
    gap = arr[a[1] + 2:b[0] - 1, max(0, x0 - 4):x0 + 40] < 140
    if gap.shape[0] == 0:
        return True
    frac = gap.mean(0)
    return frac.max() > 0.9


def group_systems(staves, arr=None):
    if arr is not None and staves:
        systems = [[staves[0]]]
        for a, b in zip(staves, staves[1:]):
            if connected(arr, a, b):
                systems[-1].append(b)
            else:
                systems.append([b])
        return systems
    if not staves:
        return []
    gaps = [staves[i + 1][0] - staves[i][1] for i in range(len(staves) - 1)]
    if not gaps:
        return [staves]
    sp = np.median([s[2] for s in staves])
    systems = [[staves[0]]]
    for g, st in zip(gaps, staves[1:]):
        if g > 9.5 * sp:  # big gap => new system
            systems.append([st])
        else:
            systems[-1].append(st)
    return systems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('outdir')
    ap.add_argument('--rotate', type=int, default=90, help='degrees CCW to make page upright')
    ap.add_argument('--dpi', type=int, default=300)
    ap.add_argument('--gap', type=float, default=None)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    raw = os.path.join(a.outdir, 'raw')
    if not glob.glob(raw + '-*.png'):
        subprocess.check_call(['pdftoppm', '-r', str(a.dpi), '-gray', '-png', a.pdf, raw])
    for f in sorted(glob.glob(raw + '-*.png')):
        n = int(f.rsplit('-', 1)[1].split('.')[0])
        im = Image.open(f).convert('L')
        if a.rotate:
            im = im.rotate(a.rotate, expand=True)
        arr, ang = deskew(np.array(im))
        Image.fromarray(arr).save(os.path.join(a.outdir, f'p{n:02d}.png'))
        staves = find_staves(arr)
        systems = group_systems(staves, arr)
        print(f'page {n}: skew {ang:+.1f}, {len(staves)} staves, systems: {[len(s) for s in systems]}')
        bounds = []
        for k, sys_ in enumerate(systems):
            sp = sys_[0][2]
            top = max(0, int(sys_[0][0] - 7 * sp))
            bot = min(arr.shape[0], int(sys_[-1][1] + 7 * sp))
            bounds.append((top, bot))
        # make crops not overlap too much: split at midpoints
        for k, (top, bot) in enumerate(bounds):
            if k > 0:
                top = max(top, (bounds[k - 1][1] + bounds[k][0]) // 2 - 0)
            crop = arr[top:bot]
            # trim horizontal whitespace
            cols = np.where((crop < 128).sum(0) > 2)[0]
            l, r = (max(0, cols[0] - 20), min(crop.shape[1], cols[-1] + 20)) if len(cols) else (0, crop.shape[1])
            crop = crop[:, l:r]
            Image.fromarray(crop).save(os.path.join(a.outdir, f'p{n:02d}_s{k + 1}.png'))
            w = crop.shape[1]
            for part, (x0, x1) in enumerate([(0, int(w * 0.55)), (int(w * 0.45), w)]):
                Image.fromarray(crop[:, x0:x1]).save(os.path.join(a.outdir, f'p{n:02d}_s{k + 1}_h{part + 1}.png'))


if __name__ == '__main__':
    main()
