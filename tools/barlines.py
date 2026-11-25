#!/usr/bin/env python3
"""Detect barlines per system on an upright page image.

    python3 tools/barlines.py work/sys/p14.png            # prints systems and barline x-positions

A barline is a thin vertical dark run that spans (almost) the whole height of every
staff of the system and the gaps between them (piano/euphonium systems are barred
through).  The system's opening line (left edge) is reported too, so the number of
bars in a system = len(xs) - 1.  Used for bar-count QA against the transcription.
"""
import sys, os
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from split_pages import find_staves, group_systems


def staff_bars(arr, stf):
    t, b, sp = stf
    dark = arr[t:b + 1] < 140
    col = dark.mean(0)
    # stems also span a staff; barlines additionally have NO notehead blob next to them:
    # require the column +-1 to be dark and +-6 px to be light at mid-staff rows (lines excluded)
    cand = np.where(col > 0.97)[0]
    groups = []
    for x in cand:
        if groups and x - groups[-1][-1] <= 2:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [int(np.mean(g)) for g in groups if len(g) <= 7]


def barlines(arr, system):
    per = [staff_bars(arr, s) for s in system]
    xs = []
    for x in per[0]:
        if all(any(abs(x - y) <= 5 for y in other) for other in per[1:]):
            xs.append(x)
    # stems can coincide in all staves rarely; require line to continue between staves of the
    # same instrument is not possible (euph separate), so accept.
    merged = []
    for x in xs:
        if merged and x - merged[-1] < 25:
            continue
        merged.append(x)
    return merged


def page_bars(path):
    arr = np.array(Image.open(path).convert('L'))
    st = find_staves(arr)
    systems = group_systems(st, arr)
    return [(s, barlines(arr, s)) for s in systems]


if __name__ == '__main__':
    for p in sys.argv[1:]:
        for i, (s, xs) in enumerate(page_bars(p), 1):
            print(f'{os.path.basename(p)} sys{i} staves={len(s)} bars={max(0, len(xs) - 1)} x={xs}')
