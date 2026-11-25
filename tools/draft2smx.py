#!/usr/bin/env python3
"""Convert an Audiveris MusicXML page into a *length-checked* SMX page (first-pass draft).

    python3 tools/draft2smx.py work/omr/p25.mxl --sys 3,3,3,3 [--first-clef bass] > transcription/p25.smx

Unlike mxl2smx.py (which just dumps the draft), this:
  * keeps ONE monophonic line per part (voice 1; other voices only fill where voice 1 is empty),
  * enforces the bar length (truncates overlong lines, pads short ones with spacers `s`),
  * adds `m sys`/`m page` headers according to --sys (bars per system),
  * attaches dynamics at their offsets, copies time-signature changes,
  * marks every line with `#? DRAFT` so that the later review pass finds them.
Chords whose notes duplicate a single pitch are collapsed.  Piano parts get clef `bass`
unless a clef change is present in the draft.
"""
import sys, argparse
from fractions import Fraction as F
import music21 as m21

sys.path.insert(0, __import__('os').path.dirname(__file__))
from mxl2smx import note_tokens, pname

DYN = {'pppp', 'ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff', 'fp', 'sf', 'sfz', 'sff'}


def qfrac(x):
    return F(x).limit_denominator(48)


def note_dur_token(n):
    return note_tokens(n)


def line_for(meas, barlen, dyns):
    voices = list(meas.voices) or [meas]
    events = []  # (offset, dur, token, kind)
    for v in voices:
        for n in v.notesAndRests:
            if n.duration.isGrace:
                continue
            o = qfrac(n.getOffsetInHierarchy(meas) if v is not meas else n.offset)
            events.append((o, qfrac(n.duration.quarterLength), n, v))
    # choose voice 1 first
    first = voices[0]
    line = []
    t = F(0)
    used = []
    v1 = [e for e in events if e[3] is first]
    for o, d, n, v in sorted(v1, key=lambda e: e[0]):
        if o < t:  # overlap -> skip
            continue
        if o > t:
            # fill gap from other voices if possible, else spacer
            fill = [e for e in events if e[3] is not first and e[0] >= t and e[0] + e[1] <= o]
            tt = t
            for o2, d2, n2, v2 in sorted(fill, key=lambda e: e[0]):
                if o2 < tt:
                    continue
                if o2 > tt:
                    line.append(('s', o2 - tt))
                    tt = o2
                line.append((n2, d2)); tt += d2
            if tt < o:
                line.append(('s', o - tt))
            t = o
        if t + d > barlen:
            d = barlen - t
            if d <= 0:
                break
        line.append((n, d)); t += d
    if t < barlen:
        line.append(('s', barlen - t))
    return line


def render(line, dyns, barlen):
    out = []
    t = F(0)
    cur_tup = None
    for item, d in line:
        if item == 's':
            out.append(spacer(d)); t += d; continue
        n = item
        tok = note_tokens(n)
        if not n.duration.tuplets:
            tok = fix_dur(tok, d)
        # dynamics at this offset
        for (o, name) in dyns:
            if abs(o - t) < F(1, 16) and name in DYN:
                tok += '\\' + name
        # tuplet handling: rely on duration type + tuplet ratio via explicit wrapper
        tups = n.duration.tuplets
        if tups:
            tp = tups[0]
            if cur_tup is None:
                out.append(f'{tp.numberNotesActual}:{tp.numberNotesNormal}{{')
                cur_tup = tp.numberNotesActual
            out.append(tok)
            cur_tup_count = getattr(render, 'c', 0) + 1
            render.c = cur_tup_count
            if tp.type == 'stop':
                out.append('}'); cur_tup = None; render.c = 0
        else:
            if cur_tup is not None:
                out.append('}'); cur_tup = None
            out.append(tok)
        t += d
    if cur_tup is not None:
        out.append('}')
    return ' '.join(out)


def _length(text):
    import dsl2mxl as d2
    try:
        items = d2.tokenize_voice(text, 'x')
        evs, L = d2.build_voice(items, 'x')
        return F(L)
    except Exception:
        return None


def fit(body, barlen):
    """Trim/pad the line so that dsl2mxl measures exactly barlen."""
    toks = body.split(' ')
    for _ in range(80):
        L = _length(' '.join(toks))
        if L is None:
            toks = toks[:-1]
            continue
        if L == barlen:
            return ' '.join(toks)
        if L < barlen:
            return ' '.join(toks + [spacer(barlen - L)])
        toks = toks[:-1]
    return 'R' if barlen == 4 else 's:1'


def fix_dur(tok, d):
    """Replace the :dur part of tok by the one that matches d (so the line adds up to the bar)."""
    import re
    base = tok.split(':')[0] if ':' in tok else tok
    # keep trailing marks (articulations etc.) after the duration
    m = re.match(r'(.*?):(\d+|B)(\.*)(.*)$', tok)
    rest = m.group(4) if m else ''
    head = m.group(1) if m else base
    for dots, mult in ((0, F(1)), (1, F(3, 2)), (2, F(7, 4))):
        b = d / mult
        for name, v in (('1', F(4)), ('2', F(2)), ('4', F(1)), ('8', F(1, 2)), ('16', F(1, 4)), ('32', F(1, 8)), ('64', F(1, 16))):
            if b == v:
                return f'{head}:{name}{"." * dots}{rest}'
    return tok


def spacer(d):
    """express a duration as spacers"""
    parts = []
    for base, name in ((F(4), '1'), (F(2), '2'), (F(1), '4'), (F(1, 2), '8'), (F(1, 4), '16'), (F(1, 8), '32')):
        while d >= base:
            parts.append(f's:{name}'); d -= base
    if d > 0:
        parts.append('s:64')
    return ' '.join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mxl')
    ap.add_argument('--sys', help='bars per system, e.g. 3,3,3,3')
    a = ap.parse_args()
    sc = m21.converter.parse(a.mxl)
    parts = list(sc.parts)
    # merge staves of the piano: Audiveris yields P1=euph, P2=RH, P3=LH
    names = ['E', 'R', 'L', 'M']
    nbars = max(len(p.getElementsByClass('Measure')) for p in parts)
    sysbars = [int(x) for x in a.sys.split(',')] if a.sys else [nbars]
    starts = {}
    c = 0
    for k, nb in enumerate(sysbars):
        starts[c] = 'm sys' if k else 'm page'
        c += nb
    barlen = F(4)
    for mi in range(nbars):
        ts = None
        for p in parts:
            ms = p.getElementsByClass('Measure')
            if mi < len(ms):
                for t in ms[mi].getElementsByClass('TimeSignature'):
                    ts = t
        if ts is not None:
            barlen = qfrac(ts.barDuration.quarterLength)
        hdr = starts.get(mi, 'm')
        if ts is not None:
            hdr += f' time={ts.ratioString}'
        print(hdr)
        for pi, p in enumerate(parts[:3]):
            ms = p.getElementsByClass('Measure')
            if mi >= len(ms):
                continue
            meas = ms[mi]
            dyns = [(qfrac(d.offset), d.value) for d in meas.recurse().getElementsByClass('Dynamic')]
            ln = line_for(meas, barlen, dyns)
            body = render(ln, dyns, barlen)
            body = fit(body, barlen)
            if all(i == 's' for i, _ in ln):
                body = 'R' if barlen == 4 else body
            print(f'{names[pi]}:  {body}   #? DRAFT')


if __name__ == '__main__':
    main()
