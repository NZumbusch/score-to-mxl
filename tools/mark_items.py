#!/usr/bin/env python3
"""Draw a red box + item number on the scan for every '#?' item in docs/open_items.csv.

    python3 tools/mark_items.py work/sys OUT.pdf
Uses the page images from split_pages.py and the barline detector to find the bar; the staff is chosen from the part.
"""
import csv, os, re, sys, glob
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from barlines import page_bars

sysdir, out = sys.argv[1], sys.argv[2]
items = list(csv.DictReader(open('docs/open_items.csv')))

def smx_systems(pg):
    """bars per system from the transcription"""
    counts = []
    for line in open(f'transcription/p{pg:02d}.smx'):
        if re.match(r'^m\b', line):
            if ' page' in line or ' sys' in line or not counts:
                counts.append(0)
            counts[-1] += 1
    return counts

try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 44)
except OSError:
    font = ImageFont.load_default()

pages = []
problems = []
for pg in sorted({int(i['Page']) for i in items}):
    path = os.path.join(sysdir, f'p{pg:02d}.png')
    im = Image.open(path).convert('RGB')
    d = ImageDraw.Draw(im)
    systems = page_bars(path)
    counts = smx_systems(pg)
    start = 0
    sysstart = []
    for c in counts:
        sysstart.append(start); start += c
    for it in items:
        if int(it['Page']) != pg:
            continue
        bp = int(it['Bar on page']) - 1
        si = max(i for i, s in enumerate(sysstart) if s <= bp) if sysstart else 0
        bi = bp - sysstart[si]
        if si >= len(systems):
            problems.append(it['#']); continue
        staves, xs = systems[si]
        n = counts[si]
        xs = list(xs)
        if len(xs) < 2:
            xs = [150, im.width - 100]
        exact = len(xs) - 1 == n
        if not exact:
            # detector disagrees with the bar count: mark the whole system line and name the bar
            problems.append(it['#'])
            # staff extent: first/last column where the staff's top line is dark
            row = np.array(im.convert('L'))[int(staves[0][0])]
            dark = np.where(row < 128)[0]
            x0, x1 = (int(dark[0]), int(dark[-1])) if len(dark) else (xs[0], xs[-1])
            xs = [x0] * bi + [x0, x1] + [x1] * (n - bi)
        label_extra = '' if exact else f' (bar {bi + 1} of this line)'
        part = it['Part']
        if part.startswith('Euph'):
            k = 0
        elif 'middle' in part:
            k = 2 if len(staves) >= 4 else len(staves) - 1
        elif 'RH' in part:
            k = 1
        else:
            k = len(staves) - 1
        t, b, sp = staves[min(k, len(staves) - 1)]
        pad = 3.5 * sp
        box = (xs[bi] + 6, t - pad, xs[bi + 1] - 6, b + pad)
        for w in range(5):
            d.rectangle((box[0] - w, box[1] - w, box[2] + w, box[3] + w), outline=(220, 0, 0))
        label = '#' + it['#'] + label_extra
        # stack labels of several items in the same box
        tx, ty = box[0] + 8, box[1] + 4
        while any(abs(tx - a) < 5 and abs(ty - c) < 5 for a, c in getattr(d, '_used', [])):
            ty += 48
        d._used = getattr(d, '_used', []) + [(tx, ty)]
        tb = d.textbbox((tx, ty), label, font=font)
        d.rectangle(tb, fill=(255, 255, 255))
        d.text((tx, ty), label, fill=(220, 0, 0), font=font)
    im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    pages.append(im)
pages[0].save(out, save_all=True, append_images=pages[1:], resolution=150, quality=80)
print('wrote', out, len(pages), 'pages; even-split fallback for items:', problems)
