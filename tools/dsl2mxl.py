#!/usr/bin/env python3
r"""Convert a hand-transcribed score in the "SMX" text notation to MusicXML.

See docs/NOTATION.md for the full language reference.  Short version:

    @title Concert Variations
    @composer Jan Bach
    @part E  "Euphonium" staves=1 clefs=bass   sound=brass.euphonium
    @part P  "Piano"     staves=2 clefs=treble,bass sound=keyboard.piano
    @voices E=E1 R=P1:1 R2=P1:2 L=P2:1 L2=P2:2      # voice key -> part,staff:voice

    m time=4/4 mm=q=66 tempo="Risoluto" sys
    E:  d3:4->\fp\< a2:2.\!\f
    R:  <c4 e4>:8( d4 e4 f4) r:2
    L:  c3:1

Usage: python3 tools/dsl2mxl.py transcription/*.smx -o out.musicxml [--mxl out.mxl]
"""
import re, sys, math, argparse, zipfile, os
from fractions import Fraction as F
from xml.sax.saxutils import escape

# ---------------------------------------------------------------- model
STEPS = 'cdefgab'
STEP_SEMI = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
ACC = {'': 0, '#': 1, '##': 2, 'b': -1, 'bb': -2, 'n': 0, '+': 0.5, '-': -0.5}
ACC_NAME = {'#': 'sharp', '##': 'double-sharp', 'b': 'flat', 'bb': 'flat-flat', 'n': 'natural'}
TYPES = {1: 'whole', 2: 'half', 4: 'quarter', 8: 'eighth', 16: '16th', 32: '32nd', 64: '64th', 128: '128th',
         0: 'breve'}
BEAMS = {8: 1, 16: 2, 32: 3, 64: 4, 128: 5}
DYNAMICS = 'pppp ppp pp p mp mf f ff fff ffff fp sf sfz sfp sfpp fz rf rfz n pf sffz'.split()


class Err(Exception):
    pass


class Pitch:
    def __init__(self, step, acc, octave, flags):
        self.step, self.acc, self.octave = step, acc, octave
        self.flags = flags  # dict: notehead, paren, staff, tie, ...

    @property
    def alter(self):
        return ACC[self.acc]

    def key(self):
        return (self.step, self.alter, self.octave)

    def midi(self):
        return 12 * (self.octave + 1) + STEP_SEMI[self.step] + self.alter


class Event:
    """note / chord / rest / space / mrest"""

    def __init__(self, kind, pitches=None, dur_base=None, dots=0):
        self.kind = kind
        self.pitches = pitches or []
        self.dur_base = dur_base  # 1,2,4,8,...  (0 = breve)
        self.dots = dots
        self.atts = []  # list of (name, arg)
        self.tuplets = []  # list of [actual, normal, start?, stop?] outer->inner
        self.grace = None  # None | 'slash' | 'noslash'
        self.offset = None
        self.duration = None  # actual duration in quarters (Fraction)
        self.staff = None
        self.line = None

    def written(self):
        if self.dur_base is None:
            return None
        b = F(8) if self.dur_base == 0 else F(4, self.dur_base)
        d, add = b, b
        for _ in range(self.dots):
            add /= 2
            d += add
        return d


# ---------------------------------------------------------------- tokenizer
TOK = re.compile(r'''
   (?P<ws>\s+|\|)
 | (?P<comment>%%.*$)
 | (?P<tupopen>(?P<tn>\d+):(?P<tm>\d+)(?P<tflags>[!b]*)\{)
 | (?P<graceopen>[gG]\{)
 | (?P<close>\})
 | (?P<chord><[^>]*>)
 | (?P<note>(?P<step>[a-g])(?P<acc>\#\#|bb|\#|b|n|\+|-(?=\d))?(?P<oct>\d))
 | (?P<rest>[rsR](?![a-z]))
 | (?P<dur>:(?P<db>\d+|B)(?P<dots>\.*))
 | (?P<flag>@[A-Za-z0-9]+(?:-[A-Za-z]+)*)
 | (?P<tie>~)
 | (?P<slur>[()\[\]])
 | (?P<artic>-[>.\-^!_+o|])
 | (?P<text>[\^_]"(?P<txt>[^"]*)")
 | (?P<fing>\#"(?P<ftxt>[^"]*)")
 | (?P<cmd>\\(?P<cname>[A-Za-z0-9]+|[<>!])(?:"(?P<carg>[^"]*)")?)
''', re.X | re.M)

STANDALONE = {'clef', 'mm', 'bb', 'nobeam', 'beam', 'tempotext'}


def parse_pitch(s, line):
    m = re.fullmatch(r'([a-g])(##|bb|#|b|n|\+|-)?(\d)((?:@[A-Za-z0-9\-]+|~)*)', s)
    if not m:
        raise Err(f'line {line}: bad pitch "{s}"')
    flags = {}
    for f in re.findall(r'@[A-Za-z0-9\-]+|~', m.group(4)):
        if f == '~':
            flags['tie'] = True
        else:
            apply_flag(flags, f[1:])
    return Pitch(m.group(1), m.group(2) or '', int(m.group(3)), flags) if True else None


def apply_flag(flags, f):
    if f in ('1', '2', '3'):
        flags['staff'] = int(f)
    elif f == 'paren':
        flags['paren'] = True
    elif f == 'hide':
        flags['hide'] = True
    elif f == 'small':
        flags['small'] = True
    elif f == 'cacc':
        flags['cacc'] = True  # cautionary accidental in parentheses
        flags['showacc'] = True
    elif f == 'na':
        flags['noacc'] = True  # pitch altered but no accidental printed (carried from earlier in bar)
    elif f == 'acc':
        flags['showacc'] = True  # cautionary/explicit accidental even if none written
    else:
        flags['notehead'] = f  # x, diamond, triangle, slash, circle-x, square, cross, ...


def tokenize_voice(text, line):
    """Return list of items. Items: Event, ('tup', n, m, flags), ('endtup',), ('grace', slash), ('endgrace',),
    ('cmd', name, arg)."""
    items = []
    pos = 0
    last_ev = None
    cur_dur = (4, 0)
    pending_pre = []  # attachments that appear before first note (applied to next)
    while pos < len(text):
        m = TOK.match(text, pos)
        if not m:
            raise Err(f'line {line}: cannot parse near "{text[pos:pos + 25]}"')
        pos = m.end()
        g = m.lastgroup
        if g in ('ws', 'comment'):
            continue
        if m.group('tupopen'):
            items.append(('tup', int(m.group('tn')), int(m.group('tm')), m.group('tflags')))
            continue
        if m.group('graceopen'):
            items.append(('grace', 'slash' if m.group(0)[0] == 'g' else 'noslash'))
            continue
        if g == 'close':
            items.append(('close',))
            continue
        if g in ('chord', 'note', 'rest'):
            if g == 'chord':
                inner = m.group('chord')[1:-1].split()
                ps = [parse_pitch(x, line) for x in inner]
                ev = Event('chord', ps)
            elif g == 'note':
                ev = Event('note', [Pitch(m.group('step'), m.group('acc') or '', int(m.group('oct')), {})])
            else:
                ev = Event({'r': 'rest', 's': 'space', 'R': 'mrest'}[m.group('rest')])
            ev.line = line
            # optional duration immediately follows
            m2 = TOK.match(text, pos)
            if m2 and m2.lastgroup == 'dur':
                db = m2.group('db')
                cur_dur = (0 if db == 'B' else int(db), len(m2.group('dots')))
                pos = m2.end()
            ev.dur_base, ev.dots = cur_dur
            if ev.dur_base not in TYPES:
                raise Err(f'line {line}: bad duration {ev.dur_base}')
            ev.atts.extend(pending_pre)
            pending_pre = []
            items.append(ev)
            last_ev = ev
            continue
        if g == 'dur':
            raise Err(f'line {line}: stray duration "{m.group(0)}"')
        # attachments
        if g == 'flag':
            if last_ev is None:
                raise Err(f'line {line}: flag without note')
            for p in last_ev.pitches:
                apply_flag(p.flags, m.group(0)[1:])
            if last_ev.kind in ('rest',) and m.group(0)[1:] in ('1', '2', '3'):
                last_ev.atts.append(('staff', int(m.group(0)[1:])))
            continue
        if g == 'tie':
            for p in last_ev.pitches:
                p.flags['tie'] = True
            continue
        att = None
        if g == 'slur':
            att = ('slur', m.group(0))
        elif g == 'artic':
            att = ('artic', m.group(0))
        elif g == 'text':
            att = ('text', (m.group(0)[0], m.group('txt')))
        elif g == 'fing':
            att = ('fing', m.group('ftxt'))
        elif g == 'cmd':
            name, arg = m.group('cname'), m.group('carg')
            if name in STANDALONE:
                items.append(('cmd', name, arg))
                continue
            att = ('cmd', (name, arg))
        if last_ev is None or (items and isinstance(items[-1], tuple) and items[-1][0] in ('tup', 'grace')
                               and last_ev is not None and False):
            pending_pre.append(att)
        else:
            last_ev.atts.append(att)
    if pending_pre:
        raise Err(f'line {line}: attachments with no note: {pending_pre}')
    return items


def build_voice(items, line):
    """Resolve tuplets/graces/durations -> flat list of Events and standalone cmds with offsets."""
    out = []
    stack = []  # ('tup', n, m, flags, firstindex) or ('grace', slash)
    t = F(0)
    for it in items:
        if isinstance(it, Event):
            ev = it
            factor = F(1)
            for s in stack:
                if s[0] == 'tup':
                    factor *= F(s[2], s[1])
            ev.tuplets = [[s[1], s[2], False, False, s[3]] for s in stack if s[0] == 'tup']
            ev.grace = next((s[1] for s in stack if s[0] == 'grace'), None)
            ev.offset = t
            if ev.grace:
                ev.duration = F(0)
            elif ev.kind == 'mrest':
                ev.duration = None  # resolved later
            else:
                ev.duration = ev.written() * factor
                # fingered (two-note) tremolo: each note sounds half its written value
                if any(a[0] == 'cmd' and re.fullmatch(r'trem[SE]\d', a[1][0]) for a in ev.atts):
                    ev.duration /= 2
                    ev.trem_half = True
                t += ev.duration
            # mark tuplet starts
            for lvl, s in enumerate([s for s in stack if s[0] == 'tup']):
                if s[4] is None:
                    s[4] = ev
                    ev.tuplets[lvl][2] = True
                s[5] = ev
            out.append(ev)
        elif it[0] == 'tup':
            stack.append(['tup', it[1], it[2], it[3], None, None])
        elif it[0] == 'grace':
            stack.append(['grace', it[1]])
        elif it[0] == 'close':
            if not stack:
                raise Err(f'line {line}: unmatched }}')
            s = stack.pop()
            if s[0] == 'tup':
                lvl = len([x for x in stack if x[0] == 'tup'])
                if s[5] is None:
                    raise Err(f'line {line}: empty tuplet')
                s[5].tuplets[lvl][3] = True
        elif it[0] == 'cmd':
            out.append(('cmd', it[1], it[2], t))
    if stack:
        raise Err(f'line {line}: unclosed {{')
    return out, t


# ---------------------------------------------------------------- score parsing
class Measure:
    def __init__(self, idx, props, line):
        self.idx = idx
        self.props = props
        self.voices = {}  # key -> (events, length)
        self.line = line
        self.length = None
        self.time = None  # (num, den, print?)
        self.number = str(idx)


def parse_props(s):
    props = {}
    for m in re.finditer(r'(\w+)(?:=("[^"]*"|\S+))?', s):
        k, v = m.group(1), m.group(2)
        if v and v.startswith('"'):
            v = v[1:-1]
        props.setdefault(k, [])
        props[k].append(v if v is not None else True)
    return {k: (v[0] if len(v) == 1 else v) for k, v in props.items()}


class Score:
    def __init__(self):
        self.title = ''
        self.subtitle = ''
        self.composer = ''
        self.parts = []  # (id, name, staves, clefs, sound, abbr)
        self.voicemap = {}  # key -> (partid, staff, voiceno)
        self.measures = []

    def parse(self, files):
        cur = None
        for fn in files:
            src = open(fn, encoding='utf-8').read().split('\n')
            for ln, raw in enumerate(src, 1):
                where = f'{os.path.basename(fn)}:{ln}'
                line = re.sub(r'(^|\s)#(?!").*$', '', raw).rstrip()
                if not line.strip():
                    continue
                try:
                    self.parse_line(line, where)
                except Err as e:
                    raise Err(f'{where}: {e}')
        return self

    def parse_line(self, line, where):
        s = line.strip()
        if s.startswith('@'):
            kw, _, rest = s[1:].partition(' ')
            if kw in ('title', 'subtitle', 'composer'):
                setattr(self, kw, rest.strip())
            elif kw == 'part':
                m = re.match(r'(\w+)\s+"([^"]*)"\s*(.*)', rest)
                pid, name, p = m.group(1), m.group(2), parse_props(m.group(3))
                self.parts.append(dict(id=pid, name=name, staves=int(p.get('staves', 1)),
                                       clefs=p.get('clefs', 'treble').split(','),
                                       sound=p.get('sound', ''), abbr=p.get('abbr', name[:4] + '.'),
                                       program=int(p.get('program', 1))))
            elif kw == 'voices':
                for m in re.finditer(r'(\w+)=(\w+?)(\d)?(?::(\d))?(?=\s|$)', rest):
                    self.voicemap[m.group(1)] = (m.group(2), int(m.group(3) or 1), int(m.group(4) or 1))
            else:
                raise Err(f'unknown directive @{kw}')
            return
        if re.match(r'm(\s|$)', s):
            self.measures.append(Measure(len(self.measures) + 1, parse_props(s[1:]), where))
            return
        m = re.match(r'(\w+):(.*)$', s)
        if not m:
            raise Err(f'cannot parse line: {s[:40]}')
        key, body = m.group(1), m.group(2)
        if not self.measures:
            raise Err('voice line before first measure')
        meas = self.measures[-1]
        direction_only = key.endswith('d') and key[:-1] in self.voicemap
        vk = key[:-1] if direction_only else key
        if vk not in self.voicemap:
            raise Err(f'unknown voice key {key}')
        items = tokenize_voice(body, where)
        evs, length = build_voice(items, where)
        k = key
        if k in meas.voices:
            raise Err(f'voice {key} given twice in measure')
        meas.voices[k] = (evs, length, direction_only)


# ---------------------------------------------------------------- MusicXML writer
def lcm(a, b):
    return a * b // math.gcd(a, b)


def time_for_length(L):
    """quarters (Fraction) -> (num, den)"""
    for den in (4, 8, 16, 32):
        n = L * den / 4
        if n.denominator == 1:
            return int(n), den
    raise Err(f'cannot make time signature for length {L}')


ARTIC = {'->': 'accent', '-.': 'staccato', '--': 'tenuto', '-^': 'strong-accent', '-!': 'staccatissimo',
         '-_': 'detached-legato', '-|': 'spiccato'}
TECH = {'-+': 'stopped', '-o': 'open-string'}


class Writer:
    def __init__(self, score, warn):
        self.s = score
        self.warn = warn

    def run(self):
        s = self.s
        # resolve measure lengths & time signatures
        prev_time = None
        for meas in s.measures:
            lens = [L for (evs, L, d) in meas.voices.values() if not d and L > 0]
            t = meas.props.get('time')
            if 'pickup' in meas.props:
                num, den = map(int, t.split('/')) if t else prev_time
                L = max(lens)
                meas.length = L
                meas.time = (num, den, (num, den) != prev_time)
                prev_time = (num, den)
                for k, (evs, Lv, d) in meas.voices.items():
                    if Lv != L and not d:
                        self.warn(f'{meas.line}: pickup m{meas.idx} voice {k} length {Lv} != {L}')
                continue
            if t:
                num, den = map(int, t.split('/'))
                L = F(num * 4, den)
            elif lens:
                L = max(lens)
                num, den = time_for_length(L)
                if prev_time and F(prev_time[0] * 4, prev_time[1]) == L:
                    num, den = prev_time
            elif prev_time:
                num, den = prev_time
                L = F(num * 4, den)
            else:
                raise Err(f'{meas.line}: cannot determine measure length')
            meas.length = L
            show = (num, den) != (prev_time or (None, None))[:2] or 'time' in meas.props
            if meas.props.get('ts') == 'hide':
                show = 'hidden'
            meas.time = (num, den, show)
            prev_time = (num, den)
            for k, (evs, Lv, d) in meas.voices.items():
                for ev in evs:
                    if isinstance(ev, Event) and ev.kind == 'mrest':
                        ev.duration = L
                        Lv = L
                if Lv != L and not d:
                    if Lv > L:
                        raise Err(f'{meas.line}: voice {k} too long: {Lv} > measure {L} (m{meas.idx})')
                    self.warn(f'{meas.line}: m{meas.idx} voice {k} short: {Lv} of {L} quarters')
                meas.voices[k] = (evs, Lv, d)
        self.fix_ties()
        self.fix_slurs()
        # divisions
        div = 1
        for meas in s.measures:
            for evs, Lv, d in meas.voices.values():
                for ev in evs:
                    vals = []
                    if isinstance(ev, Event):
                        vals = [ev.offset, ev.duration or 0]
                    else:
                        vals = [ev[3]]
                    for v in vals:
                        div = lcm(div, F(v).denominator)
            div = lcm(div, meas.length.denominator)
        self.div = div
        return self.xml()

    def fix_ties(self):
        """Make tie flags consistent: a tied note may omit its accidental (it is inherited), and a tie whose
        continuation (same step/octave, same sounding pitch) does not follow is dropped with a warning."""
        s = self.s
        removed = 0
        voice_keys = {}
        for k, (pid, staff, vno) in s.voicemap.items():
            voice_keys.setdefault(k, None)
        for k in voice_keys:
            pending = {}   # (step, octave) -> Pitch object that carries tie=True
            for meas in s.measures:
                if k not in meas.voices:
                    continue
                for ev in meas.voices[k][0]:
                    if not isinstance(ev, Event) or ev.grace:
                        continue
                    if ev.kind in ('rest', 'mrest', 'space'):
                        for pt in pending.values():
                            pt.flags.pop('tie', None); removed += 1
                        pending = {}
                        continue
                    new_pending = {}
                    for pt in ev.pitches:
                        key = (pt.step, pt.octave)
                        origin = pending.pop(key, None)
                        if origin is not None:
                            if pt.acc == '' and origin.alter != 0:
                                pt.acc = origin.acc
                                pt.flags['noacc'] = True
                            elif pt.alter == origin.alter:
                                pt.flags['noacc'] = True
                            else:
                                origin.flags.pop('tie', None); removed += 1; self.warn(f'{ev.line}: tie on {origin.step}{origin.acc}{origin.octave} dropped (next {pt.step}{pt.acc}{pt.octave})')
                                origin = None
                        if pt.flags.get('tie'):
                            new_pending[key] = pt
                    for pt in pending.values():       # tied notes that were not continued
                        pt.flags.pop('tie', None); removed += 1; self.warn(f'{ev.line}: tie on {pt.step}{pt.acc}{pt.octave} dropped (not continued by next chord)')
                    pending = new_pending
            for pt in pending.values():
                pt.flags.pop('tie', None); removed += 1
        if removed:
            self.warn(f'{removed} tie flag(s) without matching continuation were dropped (check ties near wrong chords/pitches)')

    def fix_slurs(self):
        """Drop slur starts that are never closed and stops that were never opened (per voice, slur number)."""
        s = self.s
        dropped = 0
        for k in s.voicemap:
            open_ = {}   # number -> att tuple (ev, att)
            for meas in s.measures:
                if k not in meas.voices:
                    continue
                for ev in meas.voices[k][0]:
                    if not isinstance(ev, Event):
                        continue
                    for att in list(ev.atts):
                        if att[0] != 'slur':
                            continue
                        num = 1 if att[1] in '()' else 2
                        if att[1] in ')]':
                            if num in open_:
                                del open_[num]
                            else:
                                ev.atts.remove(att); dropped += 1
                        else:
                            if num in open_:           # previous start never closed
                                oev, oatt = open_[num]
                                oev.atts.remove(oatt); dropped += 1
                            open_[num] = (ev, att)
            for oev, oatt in open_.values():
                oev.atts.remove(oatt); dropped += 1
        if dropped:
            self.warn(f'{dropped} unmatched slur marks were dropped')

    # ---------------------------------------------------------------
    def dur(self, q):
        v = q * self.div
        assert v.denominator == 1, q
        return int(v)

    def xml(self):
        s = self.s
        o = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
             '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
             '"http://www.musicxml.org/dtds/partwise.dtd">',
             '<score-partwise version="4.0">']
        o.append(f'<work><work-title>{escape(s.title)}</work-title></work>')
        o.append('<identification>')
        if s.composer:
            o.append(f'<creator type="composer">{escape(s.composer)}</creator>')
        o.append('<encoding><software>score-to-mxl dsl2mxl.py</software></encoding></identification>')
        o.append('<part-list>')
        if len(s.parts) > 1:
            pass
        for p in s.parts:
            o.append(f'<score-part id="{p["id"]}"><part-name>{escape(p["name"])}</part-name>'
                     f'<part-abbreviation>{escape(p["abbr"])}</part-abbreviation>'
                     f'<score-instrument id="{p["id"]}-I1"><instrument-name>{escape(p["name"])}</instrument-name>'
                     + (f'<instrument-sound>{p["sound"]}</instrument-sound>' if p['sound'] else '') +
                     f'</score-instrument><midi-instrument id="{p["id"]}-I1"><midi-channel>{s.parts.index(p) + 1}'
                     f'</midi-channel><midi-program>{p["program"]}</midi-program></midi-instrument></score-part>')
        o.append('</part-list>')
        for p in s.parts:
            o.extend(self.part_xml(p))
        o.append('</score-partwise>')
        return '\n'.join(o)

    def part_xml(self, p):
        s = self.s
        o = [f'<part id="{p["id"]}">']
        keys = [k for k, v in s.voicemap.items() if v[0] == p['id']]
        open_ties = {}  # (voicekey, pitchkey) -> True
        slur_state = {}
        wedge_open = {}  # staff -> bool
        trill_open = {}
        ped_open = [False]
        octave_open = {}
        first_voice_of_staff = {}
        for k in keys:
            st = s.voicemap[k][1]
            first_voice_of_staff.setdefault(st, k)
        for mi, meas in enumerate(s.measures):
            imp = ' implicit="yes"' if 'pickup' in meas.props else ''
            o.append(f'<measure number="{meas.number}"{imp}>')
            pr = meas.props
            if mi > 0 and (pr.get('sys') or pr.get('page')):
                o.append('<print new-page="yes"/>' if pr.get('page') else '<print new-system="yes"/>')
            # attributes
            attrs = []
            if mi == 0:
                attrs.append(f'<divisions>{self.div}</divisions><key print-object="no"><fifths>0</fifths></key>')
            num, den, show = meas.time
            if show:
                po = ' print-object="no"' if show == 'hidden' else ''
                sym = ' symbol="common"' if pr.get('tsym') == 'common' else ''
                attrs.append(f'<time{po}{sym}><beats>{num}</beats><beat-type>{den}</beat-type></time>')
            if mi == 0:
                if p['staves'] > 1:
                    attrs.append(f'<staves>{p["staves"]}</staves>')
                for i, c in enumerate(p['clefs']):
                    attrs.append(clef_xml(c, i + 1 if p['staves'] > 1 else None))
            if attrs:
                o.append('<attributes>' + ''.join(attrs) + '</attributes>')
            # measure-level directions only in first part
            if p is s.parts[0]:
                o.extend(self.measure_directions(meas))
            # voices
            pos = F(0)
            present = [k for k in keys if k in meas.voices or k + 'd' in meas.voices]
            for k in keys:
                for kk in (k, k + 'd'):
                    if kk not in meas.voices:
                        continue
                    evs, Lv, d = meas.voices[kk]
                    if pos > 0:
                        o.append(f'<backup><duration>{self.dur(pos)}</duration></backup>')
                        pos = F(0)
                    _, staff, vno = s.voicemap[k]
                    vnum = (staff - 1) * 4 + vno
                    pos = self.voice_xml(o, evs, Lv, d, k, staff, vnum, p, meas, open_ties, slur_state,
                                         wedge_open, trill_open, ped_open, octave_open)
            # staves with no (non-direction) voice in this measure get a whole-measure rest
            used_staves = {s.voicemap[k][1] for k in keys if k in meas.voices and not meas.voices[k][2]}
            for st in range(1, p['staves'] + 1):
                if st in used_staves:
                    continue
                if pos > 0:
                    o.append(f'<backup><duration>{self.dur(pos)}</duration></backup>')
                stf = f'<staff>{st}</staff>' if p['staves'] > 1 else ''
                o.append(f'<note><rest measure="yes"/><duration>{self.dur(meas.length)}</duration>'
                         f'<voice>{(st - 1) * 4 + 1}</voice>{stf}</note>')
                pos = meas.length
            if pos < meas.length:
                o.append(f'<forward><duration>{self.dur(meas.length - pos)}</duration></forward>')
            bar = pr.get('bar')
            if bar:
                style = {'dashed': 'dashed', 'double': 'light-light', 'final': 'light-heavy', 'none': 'none',
                         'dotted': 'dotted', 'heavy': 'heavy', 'tick': 'tick', 'short': 'short'}[bar]
                o.append(f'<barline location="right"><bar-style>{style}</bar-style></barline>')
            o.append('</measure>')
        o.append('</part>')
        return o

    def measure_directions(self, meas):
        pr = meas.props
        o = []
        if 'reh' in pr:
            o.append(f'<direction placement="above"><direction-type><rehearsal enclosure="rectangle">'
                     f'{escape(pr["reh"])}</rehearsal></direction-type></direction>')
        if 'tempo' in pr or 'mm' in pr:
            o.append(tempo_xml(pr.get('tempo'), pr.get('mm')))
        for key in ('text', 'textb'):
            vals = pr.get(key)
            if vals:
                for v in (vals if isinstance(vals, list) else [vals]):
                    pl = 'above' if key == 'text' else 'below'
                    o.append(f'<direction placement="{pl}"><direction-type><words font-style="italic">'
                             f'{escape(v)}</words></direction-type></direction>')
        return o

    def voice_xml(self, o, evs, Lv, direction_only, key, staff, vnum, p, meas, open_ties, slur_state,
                  wedge_open, trill_open, ped_open, octave_open):
        multi = p['staves'] > 1
        pos = F(0)
        # beaming
        beams = compute_beams([e for e in evs if isinstance(e, Event)], meas)
        for ev in evs:
            if not isinstance(ev, Event):
                _, name, arg, t = ev
                if t > pos:
                    o.append(f'<forward><duration>{self.dur(t - pos)}</duration></forward>')
                    pos = t
                if name == 'clef':
                    o.append('<attributes>' + clef_xml(arg, staff if multi else None) + '</attributes>')
                elif name == 'mm':
                    o.append(tempo_xml(None, arg, staff if multi else None))
                elif name == 'tempotext':
                    o.append(tempo_xml(arg, None, staff if multi else None))
                continue
            ev.staff = staff
            evstaff = staff
            if ev.pitches and 'staff' in ev.pitches[0].flags:
                evstaff = ev.pitches[0].flags['staff']
            for a in ev.atts:
                if a[0] == 'staff':
                    evstaff = a[1]
            stf = f'<staff>{evstaff}</staff>' if multi else ''
            # ----- directions attached to this event (emitted before the note)
            dirs = []
            for a in ev.atts:
                if a[0] == 'text':
                    pl = 'above' if a[1][0] == '^' else 'below'
                    txt = a[1][1]
                    style = ' font-style="italic"'
                    if txt.startswith('!'):
                        txt, style = txt[1:], ' font-weight="bold"'
                    dirs.append(f'<direction placement="{pl}"><direction-type><words{style}>{escape(txt)}</words>'
                                f'</direction-type>{stf}</direction>')
                elif a[0] == 'cmd':
                    name, arg = a[1]
                    if name in DYNAMICS:
                        if wedge_open.get(evstaff if direction_only else staff):
                            dirs.append(wedge_xml('stop', stf))
                            wedge_open[staff] = False
                        dirs.append(f'<direction placement="below"><direction-type><dynamics><{name}/></dynamics>'
                                    f'</direction-type>{stf}<sound dynamics="{DYN_VEL.get(name, 80)}"/></direction>')
                    elif name in ('<', '>'):
                        if wedge_open.get(staff):
                            dirs.append(wedge_xml('stop', stf))
                        dirs.append(wedge_xml('crescendo' if name == '<' else 'diminuendo', stf))
                        wedge_open[staff] = True
                    elif name == '!':
                        if wedge_open.get(staff):
                            dirs.append(wedge_xml('stop', stf))
                        wedge_open[staff] = False
                    elif name in ('ped', 'pedx', 'unped'):
                        typ = {'ped': 'start', 'pedx': 'change', 'unped': 'stop'}[name]
                        if name == 'ped' and ped_open[0]:
                            typ = 'change'
                        ped_open[0] = name != 'unped'
                        if typ == 'change':
                            dirs.append(f'<direction placement="below"><direction-type><pedal type="stop" line="no" '
                                        f'sign="yes"/></direction-type>{stf}</direction>')
                            typ = 'start'
                        dirs.append(f'<direction placement="below"><direction-type><pedal type="{typ}" line="no" '
                                    f'sign="yes"/></direction-type>{stf}</direction>')
                    elif name in ('8va', '8vb', '15ma', '15mb'):
                        size = 15 if name.startswith('15') else 8
                        typ = 'down' if name.endswith('a') else 'up'
                        dirs.append(f'<direction placement="{"above" if typ == "down" else "below"}"><direction-type>'
                                    f'<octave-shift type="{typ}" size="{size}"/></direction-type>{stf}</direction>')
                        octave_open[staff] = size
                    elif name == '8vx':
                        dirs.append(f'<direction><direction-type><octave-shift type="stop" size='
                                    f'"{octave_open.get(staff, 8)}"/></direction-type>{stf}</direction>')
            if not direction_only:
                o.extend(dirs)
            # ----- the note(s)
            if ev.kind == 'space' or direction_only:
                if direction_only:
                    o.extend(dirs)
                if ev.duration:
                    o.append(f'<forward><duration>{self.dur(ev.duration)}</duration></forward>')
                pos += ev.duration or 0
                continue
            cmds = {a[1][0]: a[1][1] for a in ev.atts if a[0] == 'cmd'}
            pitches = ev.pitches if ev.kind in ('note', 'chord') else [None]
            for pi, pt in enumerate(pitches):
                n = ['<note' + (' print-object="no"' if pt is not None and pt.flags.get('hide') else '') + '>']
                if ev.grace:
                    n.append('<grace slash="yes"/>' if ev.grace == 'slash' else '<grace/>')
                if pi > 0:
                    n.append('<chord/>')
                if pt is None:
                    n.append('<rest measure="yes"/>' if ev.kind == 'mrest' else '<rest/>')
                else:
                    alt = f'<alter>{fmt_alter(pt.alter)}</alter>' if pt.alter else ''
                    n.append(f'<pitch><step>{pt.step.upper()}</step>{alt}<octave>{pt.octave}</octave></pitch>')
                if not ev.grace:
                    n.append(f'<duration>{self.dur(ev.duration)}</duration>')
                tie_start = pt is not None and pt.flags.get('tie')
                tie_stop = pt is not None and open_ties.pop((key, pt.key()), False)
                if tie_stop:
                    n.append('<tie type="stop"/>')
                if tie_start:
                    n.append('<tie type="start"/>')
                n.append(f'<voice>{vnum}</voice>')
                if ev.kind != 'mrest':
                    n.append(f'<type>{TYPES[ev.dur_base]}</type>' + '<dot/>' * ev.dots)
                if pt is not None and self._acc_needed(p, meas, pt, evstaff):
                    an = ACC_NAME.get(pt.acc, 'natural') if pt.acc not in ('+', '-') else \
                        ('quarter-sharp' if pt.acc == '+' else 'quarter-flat')
                    par = ' parentheses="yes"' if pt.flags.get('cacc') else ''
                    n.append(f'<accidental{par}>{an}</accidental>')
                if (ev.tuplets or getattr(ev, 'trem_half', False)) and not ev.grace:
                    a_, nn = (2, 1) if getattr(ev, 'trem_half', False) else (1, 1)
                    for t in ev.tuplets:
                        a_ *= t[0]
                        nn *= t[1]
                    g = math.gcd(a_, nn)
                    n.append(f'<time-modification><actual-notes>{a_ // g * g}</actual-notes>'
                             f'<normal-notes>{nn // g * g}</normal-notes></time-modification>')
                if pt is not None:
                    nh = pt.flags.get('notehead')
                    par = pt.flags.get('paren')
                    if nh or par:
                        nhname = {'dia': 'diamond', 'x': 'x', 'tri': 'triangle', 'sq': 'square',
                                  'cx': 'circle-x', 'slash': 'slash', 'cross': 'cross'}.get(nh, nh or 'normal')
                        fill = ''
                        if nh in ('diamond', 'dia') and ev.dur_base and ev.dur_base >= 4:
                            fill = ''
                        n.append(f'<notehead{" parentheses=\"yes\"" if par else ""}{fill}>{nhname}</notehead>')
                elif ev.kind == 'rest':
                    pass
                if multi:
                    pst = pt.flags.get('staff', evstaff) if pt is not None else evstaff
                    n.append(f'<staff>{pst}</staff>')
                if pi == 0 and id(ev) in beams:
                    n.extend(f'<beam number="{i + 1}">{b}</beam>' for i, b in enumerate(beams[id(ev)]))
                # notations
                nt = []
                if tie_stop:
                    nt.append('<tied type="stop"/>')
                if tie_start:
                    nt.append('<tied type="start"/>')
                if pt is not None and tie_start:
                    open_ties[(key, pt.key())] = True
                if pi == 0:
                    nt.extend(self.first_note_notations(ev, cmds, slur_state, key, trill_open))
                if 'arp' in cmds:
                    nt.append('<arpeggiate/>')
                if 'glstop' in cmds and pi == 0:
                    kind = getattr(self, '_gl', {}).get(key, 'slide')
                    nt.append(f'<{kind} type="stop"/>')
                if 'gl' in cmds and pi == 0:
                    if not hasattr(self, '_gl'):
                        self._gl = {}
                    self._gl[key] = 'glissando' if cmds['gl'] == 'wavy' else 'slide'
                    nt.append('<glissando type="start" line-type="wavy"/>' if cmds['gl'] == 'wavy'
                              else '<slide type="start" line-type="solid"/>')
                if nt:
                    n.append('<notations>' + ''.join(nt) + '</notations>')
                n.append('</note>')
                o.append(''.join(n))
            pos += ev.duration
        if pos < meas.length and not direction_only:
            o.append(f'<forward><duration>{self.dur(meas.length - pos)}</duration></forward>')
            pos = meas.length
        return pos

    def _acc_needed(self, part, meas, pt, staff):
        """Print an accidental unless the same pitch with the same alteration already occurred
        earlier in this measure on this staff (standard engraving rule).  @acc/@cacc force it,
        @na suppresses it."""
        st = self.__dict__.setdefault('_accstate', {})
        k = (part['id'], meas.idx, pt.flags.get('staff', staff))
        d = st.setdefault(k, {})
        prev = d.get((pt.step, pt.octave))
        d[(pt.step, pt.octave)] = pt.alter
        if pt.flags.get('noacc'):
            return False
        if pt.flags.get('showacc'):
            return True
        if not pt.acc:
            return prev is not None and prev != 0   # natural needed after an earlier alteration
        return prev is None or prev != pt.alter

    def first_note_notations(self, ev, cmds, slur_state, key, trill_open):
        nt = []
        # tuplets
        if not ev.grace:
            for lvl, t in enumerate(ev.tuplets):
                flags = t[4] or ''
                br = ' bracket="no"' if 'b' not in flags and False else ''
                if '!' in flags:
                    br = ' show-number="none" bracket="no"'
                elif 'b' in flags:
                    br = ' bracket="yes"'
                if t[2]:
                    nt.append(f'<tuplet type="start" number="{lvl + 1}"{br}>'
                              f'<tuplet-actual><tuplet-number>{t[0]}</tuplet-number></tuplet-actual>'
                              f'<tuplet-normal><tuplet-number>{t[1]}</tuplet-number></tuplet-normal></tuplet>')
                if t[3]:
                    nt.append(f'<tuplet type="stop" number="{lvl + 1}"/>')
        # slurs: stops before starts
        for a in ev.atts:
            if a[0] == 'slur' and a[1] in ')]':
                num = 1 if a[1] == ')' else 2
                if slur_state.get((key, num)):
                    nt.append(f'<slur type="stop" number="{num}"/>')
                    slur_state[(key, num)] = False
                else:
                    self.warn(f'{ev.line}: slur stop without start in voice {key}')
        for a in ev.atts:
            if a[0] == 'slur' and a[1] in '([':
                num = 1 if a[1] == '(' else 2
                nt.append(f'<slur type="start" number="{num}"/>')
                slur_state[(key, num)] = True
        arts = [ARTIC[a[1]] for a in ev.atts if a[0] == 'artic' and a[1] in ARTIC]
        extra = []
        if 'breath' in cmds:
            extra.append('<breath-mark/>')
        if 'caesura' in cmds:
            extra.append('<caesura/>')
        if arts or extra:
            nt.append('<articulations>' + ''.join(f'<{x}/>' for x in arts) + ''.join(extra) + '</articulations>')
        tech = [TECH[a[1]] for a in ev.atts if a[0] == 'artic' and a[1] in TECH]
        fing = [a[1] for a in ev.atts if a[0] == 'fing'][::-1]  # MusicXML stacks bottom-up
        techx = ''.join(f'<{x}/>' for x in tech) + ''.join(f'<fingering>{escape(f)}</fingering>' for f in fing)
        if 'harm' in cmds:
            techx += '<harmonic/>'
        if techx:
            nt.append(f'<technical>{techx}</technical>')
        orn = []
        if 'tr' in cmds or 'trl' in cmds:
            orn.append('<trill-mark/>')
        if 'trl' in cmds:
            orn.append('<wavy-line type="start"/>')
            trill_open[key] = True
        if 'trx' in cmds:
            orn.append('<wavy-line type="stop"/>')
            trill_open[key] = False
        for c, v in cmds.items():
            if c.startswith('trem') and c[4:].isdigit():
                orn.append(f'<tremolo type="single">{c[4:]}</tremolo>')
            if c.startswith('tremS') and c[5:].isdigit():
                orn.append(f'<tremolo type="start">{c[5:]}</tremolo>')
            if c.startswith('tremE') and c[5:].isdigit():
                orn.append(f'<tremolo type="stop">{c[5:]}</tremolo>')
        if 'tracc' in cmds:
            orn.append(f'<accidental-mark>{ACC_NAME.get(cmds["tracc"], cmds["tracc"])}</accidental-mark>')
        if 'turn' in cmds:
            orn.append('<turn/>')
        if 'mordent' in cmds:
            orn.append('<mordent/>')
        if orn:
            nt.append('<ornaments>' + ''.join(orn) + '</ornaments>')
        if 'fermata' in cmds:
            nt.append('<fermata type="upright"/>')
        if 'fermataS' in cmds:
            nt.append('<fermata type="upright">angled</fermata>')
        if 'fermataL' in cmds:
            nt.append('<fermata type="upright">square</fermata>')
        return nt


DYN_VEL = dict(pppp=20, ppp=30, pp=40, p=55, mp=70, mf=85, f=100, ff=115, fff=125, ffff=127, fp=100, sf=110,
               sfz=115, sfp=110, fz=110, rf=105, rfz=110, n=10)


def fmt_alter(a):
    return str(int(a)) if a == int(a) else str(a)


def wedge_xml(t, stf):
    return f'<direction placement="below"><direction-type><wedge type="{t}"/></direction-type>{stf}</direction>'


def clef_xml(c, number=None):
    num = f' number="{number}"' if number else ''
    sign, line, oc = {'treble': ('G', 2, 0), 'bass': ('F', 4, 0), 'alto': ('C', 3, 0), 'tenor': ('C', 4, 0),
                      'treble8vb': ('G', 2, -1), 'treble8va': ('G', 2, 1), 'bass8vb': ('F', 4, -1),
                      'perc': ('percussion', None, 0)}[c]
    x = f'<clef{num}><sign>{sign}</sign>' + (f'<line>{line}</line>' if line else '')
    if oc:
        x += f'<clef-octave-change>{oc}</clef-octave-change>'
    return x + '</clef>'


def tempo_xml(text, mm, staff=None):
    parts = []
    snd = ''
    if text:
        parts.append(f'<direction-type><words font-weight="bold">{escape(text)}</words></direction-type>')
    if mm:
        m = re.fullmatch(r'(q|h|e|w|s)(\.?)=(\d+(?:\.\d+)?)', mm)
        if not m:
            raise Err(f'bad mm "{mm}"')
        unit = {'q': 'quarter', 'h': 'half', 'e': 'eighth', 'w': 'whole', 's': '16th'}[m.group(1)]
        qlen = {'q': 1, 'h': 2, 'e': 0.5, 'w': 4, 's': 0.25}[m.group(1)] * (1.5 if m.group(2) else 1)
        bpm = float(m.group(3))
        dot = '<beat-unit-dot/>' if m.group(2) else ''
        parts.append(f'<direction-type><metronome parentheses="no"><beat-unit>{unit}</beat-unit>{dot}'
                     f'<per-minute>{m.group(3)}</per-minute></metronome></direction-type>')
        snd = f'<sound tempo="{round(bpm * qlen, 3):g}"/>'
    stf = f'<staff>{staff}</staff>' if staff else ''
    return '<direction placement="above">' + ''.join(parts) + stf + snd + '</direction>'


def compute_beams(evs, meas):
    """Simple automatic beaming. Returns {id(ev): [beam values per level]}"""
    num, den, _ = meas.time
    # beat length for grouping
    if den == 8 and num % 3 == 0 and num > 3:
        beat = F(3, 2)
    elif den >= 8:
        beat = F(1, 2) if den == 8 else F(1, 4)
        beat = F(3, 2) if (den == 8 and num % 3 == 0) else F(1)
    else:
        beat = F(1)
    groups = []
    cur = []
    curkey = None

    def flush():
        nonlocal cur
        if len(cur) >= 2:
            groups.append(cur)
        cur = []

    for ev in evs:
        beamable = ev.kind in ('note', 'chord') and ev.dur_base and ev.dur_base >= 8
        if ev.grace:
            key = ('g', id(curkey) if False else None)
            if not beamable or (cur and not cur[-1].grace):
                flush()
            if beamable:
                cur.append(ev)
            continue
        if cur and cur[-1].grace:
            flush()
        if any(a[0] == 'cmd' and a[1][0] == 'nb' for a in ev.atts):
            flush()
        if not beamable:
            flush()
            continue
        # group key: outermost tuplet group id, else beat index
        if ev.tuplets:
            key = ('t', ev.tuplets[0][0], ev.tuplets[0][1], tuple_start_id(ev))
        else:
            key = ('b', int(ev.offset // beat))
        if cur and key != curkey:
            flush()
        cur.append(ev)
        curkey = key
    flush()
    res = {}
    for g in groups:
        levels = [BEAMS.get(e.dur_base, 0) for e in g]
        vals = [[] for _ in g]
        for lvl in range(1, max(levels) + 1):
            for i, e in enumerate(g):
                if levels[i] < lvl:
                    continue
                if lvl == 1:
                    vals[i].append('begin' if i == 0 else ('end' if i == len(g) - 1 else 'continue'))
                    continue
                prev = i > 0 and levels[i - 1] >= lvl
                nxt = i < len(g) - 1 and levels[i + 1] >= lvl
                if prev and nxt:
                    vals[i].append('continue')
                elif prev:
                    vals[i].append('end')
                elif nxt:
                    vals[i].append('begin')
                else:
                    vals[i].append('backward hook' if i > 0 else 'forward hook')
        for e, v in zip(g, vals):
            res[id(e)] = v
    return res


_tup_ids = {}


def tuple_start_id(ev):
    # events in the same outer tuplet share the object that started it; approximate via offset bucket
    return getattr(ev, '_tupgroup', None)


def assign_tuplet_groups(score):
    for meas in score.measures:
        for evs, L, d in meas.voices.values():
            gid = 0
            for ev in evs:
                if isinstance(ev, Event) and ev.tuplets:
                    if ev.tuplets[0][2]:
                        gid += 1
                    ev._tupgroup = gid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--mxl', help='also write compressed .mxl')
    ap.add_argument('--strict', action='store_true', help='treat warnings as errors')
    a = ap.parse_args()
    warnings = []
    try:
        sc = Score().parse(a.files)
        assign_tuplet_groups(sc)
        off = 0 if sc.measures and 'pickup' in sc.measures[0].props else 1
        for i, m in enumerate(sc.measures):
            m.number = str(i + off)
        xml = Writer(sc, warnings.append).run()
    except Err as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
    for w in warnings:
        print('warning:', w, file=sys.stderr)
    open(a.out, 'w', encoding='utf-8').write(xml)
    if a.mxl:
        with zipfile.ZipFile(a.mxl, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('mimetype', 'application/vnd.recordare.musicxml', compress_type=zipfile.ZIP_STORED)
            z.writestr('META-INF/container.xml',
                       '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles>'
                       '<rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/>'
                       '</rootfiles></container>')
            z.writestr('score.musicxml', xml)
    print(f'wrote {a.out}: {len(sc.measures)} measures, divisions={Writer.__dict__ and "ok"}', file=sys.stderr)
    if a.strict and warnings:
        sys.exit(2)


if __name__ == '__main__':
    main()
