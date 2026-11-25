#!/usr/bin/env python3
"""Turn an Audiveris (or any) MusicXML file into an SMX *draft* for manual correction.

    python3 tools/mxl2smx.py work/omr/p05.mxl > work/draft_p05.smx

Each measure becomes an `m` line followed by one voice line per (part, staff, voice):
    P2s1v1: <c4 e4>:8( d4 ...
The line keys are placeholders: rename them to the voice keys of the header
(E, R, R2, M, L, ...) while checking against the scan.  Only pitches, rhythms,
tuplets, rests, ties, chords, graces, slurs and accents/staccato/tenuto are carried over;
dynamics and text are listed as comments.
"""
import sys
from fractions import Fraction as F
import music21 as m21

DUR = {4.0: '1', 2.0: '2', 1.0: '4', 0.5: '8', 0.25: '16', 0.125: '32', 0.0625: '64', 8.0: 'B'}


def pname(p):
    acc = ''
    if p.accidental is not None:
        acc = {'sharp': '#', 'flat': 'b', 'natural': 'n', 'double-sharp': '##', 'double-flat': 'bb'}.get(
            p.accidental.name, '')
        if p.accidental.name == 'natural' and not p.accidental.displayStatus:
            acc = ''
    return p.step.lower() + acc + str(p.octave)


def dur_token(n):
    d = n.duration
    t = d.type
    base = {'whole': '1', 'half': '2', 'quarter': '4', 'eighth': '8', '16th': '16', '32nd': '32', '64th': '64',
            'breve': 'B'}.get(t)
    if base is None:
        return ':4'
    return ':' + base + '.' * d.dots


def note_tokens(n):
    if n.isRest:
        tok = 'r'
    elif n.isChord:
        tok = '<' + ' '.join(pname(p) for p in n.pitches) + '>'
    else:
        tok = pname(n.pitch)
    tok += dur_token(n)
    if not n.isRest and n.tie is not None and n.tie.type in ('start', 'continue'):
        tok += '~'
    for a in n.articulations:
        tok += {'Accent': '->', 'Staccato': '-.', 'Tenuto': '--', 'StrongAccent': '-^',
                'Staccatissimo': '-!'}.get(type(a).__name__, '')
    for e in n.expressions:
        if type(e).__name__ == 'Fermata':
            tok += '\\fermata'
    return tok


def voice_line(stream):
    toks = []
    open_tup = None
    for n in stream.notesAndRests:
        if n.duration.isGrace:
            toks.append('g{' + note_tokens(n).replace(':', ':', 1) + '}')
            continue
        tups = n.duration.tuplets
        if tups:
            t = tups[0]
            if t.type == 'start' or open_tup is None:
                if open_tup:
                    toks.append('}')
                toks.append(f'{t.numberNotesActual}:{t.numberNotesNormal}{{')
                open_tup = t
            toks.append(note_tokens(n))
            if t.type == 'stop':
                toks.append('}')
                open_tup = None
        else:
            if open_tup:
                toks.append('}')
                open_tup = None
            toks.append(note_tokens(n))
    if open_tup:
        toks.append('}')
    return ' '.join(toks)


def main():
    sc = m21.converter.parse(sys.argv[1])
    parts = list(sc.parts)
    nmeas = max(len(p.getElementsByClass('Measure')) for p in parts)
    for mi in range(nmeas):
        lines = []
        ts = None
        for pi, p in enumerate(parts, 1):
            ms = p.getElementsByClass('Measure')
            if mi >= len(ms):
                continue
            meas = ms[mi]
            for t in meas.getElementsByClass('TimeSignature'):
                ts = t.ratioString
            for c in meas.recurse().getElementsByClass('Clef'):
                nm = {'F': 'bass', 'G': 'treble'}.get(c.sign, c.sign)
                lines.append(f'  # P{pi}: clef {nm} @ {c.offset}')
            for d in meas.recurse().getElementsByClass('Dynamic'):
                lines.append(f'  # P{pi}: dyn {d.value} @ {d.offset}')
            voices = list(meas.voices) or [meas]
            for vi, v in enumerate(voices, 1):
                if not v.notesAndRests:
                    continue
                if all(n.isRest for n in v.notesAndRests):
                    continue
                lines.append(f'P{pi}v{vi}: ' + voice_line(v))
        print('m' + (f' time={ts}' if ts else '') + f'   # draft m{mi + 1}')
        for l in lines:
            print(l)


if __name__ == '__main__':
    main()
