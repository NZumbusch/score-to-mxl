#!/usr/bin/env python3
"""Render a MusicXML file to PNG pages with verovio (for proof-reading against the scan).

    python3 tools/render.py score.musicxml OUTDIR [--measures 1-12] [--width 2100] [--breaks encoded|auto]

With --breaks encoded the <print new-system/new-page> hints from the transcription
are honoured, so rendered systems line up with the original systems.
"""
import argparse, os, re
import verovio, cairosvg

ap = argparse.ArgumentParser()
ap.add_argument('xml'); ap.add_argument('outdir')
ap.add_argument('--measures', help='e.g. 5-20 (MusicXML measure numbers)')
ap.add_argument('--width', type=int, default=2200)
ap.add_argument('--height', type=int, default=3000)
ap.add_argument('--breaks', default='encoded')
ap.add_argument('--scale', type=int, default=40)
ap.add_argument('--prefix', default='r')
a = ap.parse_args()
os.makedirs(a.outdir, exist_ok=True)
tk = verovio.toolkit()
tk.setOptions({'pageWidth': a.width, 'pageHeight': a.height, 'scale': a.scale, 'breaks': a.breaks,
               'adjustPageHeight': True, 'footer': 'none', 'header': 'none', 'mnumInterval': 1,
               'svgRemoveXlink': True})
tk.loadFile(a.xml)
if a.measures:
    lo, hi = a.measures.split('-')
    tk.select({'measureRange': f'{lo}-{hi}'})
    tk.redoLayout()
n = tk.getPageCount()
for p in range(1, n + 1):
    svg = tk.renderToSVG(p)
    fn = os.path.join(a.outdir, f'{a.prefix}{p:02d}.png')
    cairosvg.svg2png(bytestring=svg.encode(), write_to=fn, output_width=a.width // 2 * 1, background_color='white')
    print(fn)
