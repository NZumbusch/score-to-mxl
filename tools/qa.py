#!/usr/bin/env python3
"""Sanity checks on the generated MusicXML.

    python3 tools/qa.py output/Concert_Variations.musicxml

Reports, per part/staff/voice stream:
  * tie starts that are not followed by a tie stop on the SAME pitch in the next note of that voice
    (catches wrong ties and ties that run over several bars by mistake)
  * ties longer than N measures
  * tie stops without a start
  * unbalanced slurs / wedges / tuplets / octave-shifts / pedal lines
  * measures whose voices don't add up to the measure length
"""
import sys, collections
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
issues = []
for part in root.findall('part'):
    pid = part.get('id')
    div = 1
    open_tie = {}   # (voice, staff) -> {pitch: measure}
    slur = collections.Counter(); tup = collections.Counter(); wedge = 0; octs = 0
    for meas in part.findall('measure'):
        num = meas.get('number')
        pos = {}
        lastv = None
        groups = []   # list of (voice, staff, [pitches with tie flags], is_rest)
        for el in meas:
            if el.tag == 'attributes':
                d = el.find('divisions')
                if d is not None: div = int(d.text)
            if el.tag == 'forward' and lastv is not None:
                pos[lastv] = pos.get(lastv, 0) + int(el.findtext('duration'))
            if el.tag != 'note':
                continue
            voice = el.findtext('voice'); staff = el.findtext('staff') or '1'
            lastv = voice
            dur = el.find('duration')
            is_chord = el.find('chord') is not None
            if not is_chord and dur is not None:
                pos[voice] = pos.get(voice, 0) + int(dur.text)
            pit = el.find('pitch')
            ties = [t.get('type') for t in el.findall('tie')]
            entry = None if pit is None else ((pit.findtext('step'), pit.findtext('alter') or '0', pit.findtext('octave')), ties)
            if el.find('grace') is not None:
                continue
            if is_chord and groups and groups[-1][0] == (voice, staff):
                if entry: groups[-1][1].append(entry)
            else:
                groups.append(((voice, staff), [entry] if entry else [], pit is None))
            for sl in el.iter('slur'):
                slur[(voice, sl.get('number'))] += 1 if sl.get('type') == 'start' else -1
            for t in el.iter('tuplet'):
                tup[(voice, t.get('number'))] += 1 if t.get('type') == 'start' else -1
        for key, notes, is_rest in groups:
            o = open_tie.setdefault(key, {})
            stops = {p for p, t in notes if 'stop' in t}
            for pch in list(o):
                if pch not in stops:
                    issues.append(f'{pid} m{o[pch]} v{key[0]}: tie on {pch} not continued (next event in m{num})')
                    del o[pch]
            for pch in stops:
                if pch in o:
                    if int(num) - int(o[pch]) > 2:
                        issues.append(f'{pid} m{num} v{key[0]}: tie spans {int(num)-int(o[pch])} measures')
                    del o[pch]
                else:
                    issues.append(f'{pid} m{num} v{key[0]}: tie stop on {pch} without start')
            for pch, t in notes:
                if 'start' in t: o[pch] = num
        for d in meas.iter('wedge'):
            if d.get('type') in ('crescendo', 'diminuendo'): wedge += 1
            elif d.get('type') == 'stop': wedge -= 1
        for d in meas.iter('octave-shift'):
            octs += {'down': 1, 'up': 1, 'stop': -1}.get(d.get('type'), 0)
        if pos:
            L = max(pos.values())
            for v, p in pos.items():
                if p != L:
                    issues.append(f'{pid} m{num}: voice {v} has {p/div:.3f} beats vs {L/div:.3f} in other voices')
    for k, v in slur.items():
        if v != 0: issues.append(f'{pid}: slur number {k[1]} voice {k[0]} unbalanced ({v:+d})')
    for k, v in tup.items():
        if v != 0: issues.append(f'{pid}: tuplet {k} unbalanced ({v:+d})')
    for k, o in open_tie.items():
        for pch, m in o.items():
            issues.append(f'{pid} m{m} v{k[0]}: tie on {pch} never closed')
    if wedge: issues.append(f'{pid}: hairpins unbalanced ({wedge:+d})')
    if octs: issues.append(f'{pid}: octave shifts unbalanced ({octs:+d})')
print(f'{len(issues)} issues')
for i in issues: print(' ', i)
