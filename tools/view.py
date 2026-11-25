#!/usr/bin/env python3
"""Crop staves from an upright page image for close reading.

    python3 tools/view.py PAGEPNG FIRST LAST [NPARTS] [--out DIR] [--zoom Z]

FIRST/LAST are 1-based staff indices on the page (as found by split_pages.find_staves).
Writes DIR/view_<page>_<first>-<last>_<k>.png, split horizontally into NPARTS
overlapping pieces.  Prints staff list when FIRST=0.
"""
import sys, os, argparse
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from split_pages import find_staves

ap = argparse.ArgumentParser()
ap.add_argument('page'); ap.add_argument('first', type=int); ap.add_argument('last', type=int, nargs='?')
ap.add_argument('nparts', type=int, nargs='?', default=2)
ap.add_argument('--out', default=os.environ.get('VIEWDIR', '/tmp'))
ap.add_argument('--zoom', type=float, default=1.0)
ap.add_argument('--x0', type=float, default=0.0); ap.add_argument('--x1', type=float, default=1.0)
ap.add_argument('--ypx', help='explicit pixel rows y0,y1 instead of staff indices')
ap.add_argument('--clefs', help='comma list of clefs (treble/bass/-) for the staves FIRST..LAST: draws a pitch grid')
ap.add_argument('--pad', type=float, default=6.0, help='margin above/below in staff spaces')
a = ap.parse_args()
arr = np.array(Image.open(a.page).convert('L'))
st = find_staves(arr)
if a.first == 0:
    for i, s in enumerate(st, 1):
        print(i, s)
    sys.exit()
last = a.last or a.first
sp = st[0][2]
if a.ypx:
    top, bot = map(int, a.ypx.split(','))
else:
    top = max(0, int(st[a.first - 1][0] - a.pad * sp)); bot = min(arr.shape[0], int(st[last - 1][1] + a.pad * sp))
crop = arr[top:bot]
grid = None
if a.clefs:
    from PIL import ImageDraw, ImageFont
    clefs = a.clefs.split(',')
    rgb = Image.fromarray(crop).convert('RGB')
    dr = ImageDraw.Draw(rgb)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
    except Exception:
        font = ImageFont.load_default()
    names = 'CDEFGAB'
    for si, cl in zip(range(a.first, last + 1), clefs):
        if cl == '-':
            continue
        t, b, spc = st[si - 1]
        spc = (b - t) / 4.0
        # diatonic index of bottom line: treble E4, bass G2, alto F3, tenor D3
        base = {'treble': 4 * 7 + 2, 'bass': 2 * 7 + 4, 'alto': 3 * 7 + 3, 'tenor': 3 * 7 + 1}[cl]
        lo_lim = (st[si - 2][1] + t) / 2 if si >= 2 else -1e9  # midpoint to staff above
        hi_lim = (b + st[si][0]) / 2 if si < len(st) else 1e9
        for k in range(-14, 23):  # half-space steps from bottom line, positive = up
            yabs = b - k * spc / 2
            if yabs < lo_lim or yabs > hi_lim:
                continue
            y = yabs - top
            if y < 0 or y >= crop.shape[0]:
                continue
            d = base + k
            nm = names[d % 7] + str(d // 7)
            on_line = k % 2 == 0
            inside = 0 <= k <= 8
            if on_line and not inside:
                for x in range(0, rgb.width, 12):
                    dr.line([(x, y), (x + 5, y)], fill=(120, 170, 255), width=1)
            col = (230, 60, 60) if on_line else (40, 150, 40)
            for x in range(8, rgb.width, 330):
                dr.text((x + (0 if on_line else 22), y - 7), nm, fill=col, font=font)
    grid = rgb
cols = np.where((crop < 128).sum(0) > 2)[0]
l, r = cols[0], cols[-1]
W = r - l
l, r = int(l + a.x0 * W), int(l + a.x1 * W)
W = r - l
n = a.nparts
ov = int(0.04 * W)
base = os.path.splitext(os.path.basename(a.page))[0]
for k in range(n):
    x0 = max(l, l + k * W // n - ov); x1 = min(r, l + (k + 1) * W // n + ov)
    im = grid.crop((x0, 0, x1, grid.height)) if grid is not None else Image.fromarray(crop[:, x0:x1])
    if a.zoom != 1:
        im = im.resize((int(im.width * a.zoom), int(im.height * a.zoom)), Image.LANCZOS)
    fn = os.path.join(a.out, f'view_{base}_{a.first}-{last}_{k + 1}.png')
    im.save(fn); print(fn, im.size)
