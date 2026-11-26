# Handoff: continuing the Concert Variations transcription

## Status
- See docs/STATUS.md for the current page-by-page state (all pages transcribed; page 21 piano is the weakest).
- Page 22 has NO Audiveris draft; its euphonium line is good but the piano pitches are best-effort (#?) and need a second pass.
- Page 21 has several approximate spots marked `#?` (arpeggio notes in bar 268, the Coro chord spellings and multiphonic notes, the senza-misura 16ths). A second pass on these is still needed.
- **Next: page 25**, then pages 26–29 (fugue; subject = `r16 g2 a2 g2 | bb2-> a2 ab2 g2 | r16 g2 an2 g2 | bb2-> a2 ab2 g2`, see top of p23.smx). Page 23: fugue bars 2-6 euph pitches and all piano are best-effort `#?`. Page 30 is blank.
- Audiveris drafts exist for every page except 22 and 28 (it crashed on those two), but they live in
  `work/omr/` (git-ignored). Recreate them with `tools/setup_audiveris.sh` plus the batch command in `docs/FINDINGS.md`.

## Per-page workflow (it works; keep it)
1. `python3 tools/barlines.py work/sys/pNN.png` gives the bar count per system. Each system starts with `m sys`, each page with `m page`.
2. `python3 tools/mxl2smx.py work/omr/pNN.mxl` gives the Audiveris draft. Use it for pitches of simple lines;
   its rhythms and voices in dense piano writing are often wrong.
3. Look at each system: `python3 tools/heads.py work/sys/pNN.png FIRST LAST "bass,treble>bass@1500,bass" 2 --out $SCRATCH --zoom 1.0`.
   This labels detected noteheads with pitch names and draws a page-x ruler; give clef changes as `clef@x`.
   `tools/view.py` does plain crops. Zoom into dense spots with a small PIL crop.
4. Write `transcription/pNN.smx`, then run
   `python3 tools/dsl2mxl.py transcription/00_header.smx transcription/p*.smx --breaks -o work/test.musicxml` (`--breaks` keeps the scan's system breaks for render comparison; the output/ files have no layout so Dorico lays them out itself).
   Fix every "voice short/too long" and "slur stop without start" warning.
5. `python3 tools/render.py work/test.musicxml work/render --width 2400` and compare `work/render/rNN.png` with the scan.
6. `./build.sh`, then commit and push.

## Notation cheat-sheet (see existing pages for many examples)
- Voices: `E` = euphonium; piano `R`/`R2`/`R3` = top staff, `M` = middle staff (only where the original has 3 piano staves), `L`/`L2`/`L3` = bottom staff.
  `Ed:` is a direction-only line (e.g. `\mm"q=132"` in the middle of a bar).
- Notes: `c#4:8.` (dotted eighth), `<c4 e4>:2`, rest `r:4`, invisible spacer `s:4`, whole-bar rest `R`, tie `~`, slurs `( )`.
  Duration is sticky: once given, it carries to the following notes.
- Per-note flags: `@3` cross-staff (staff 1/2/3), `@dia` diamond (sung pitch), `@paren`, `@cacc` cautionary accidental, `@na` hide accidental, `@acc` force accidental.
- Tuplets: `3:2{ … }` (nested OK); `4:6{ …16ths }` for "4 in the time of 6". Graces: `g{ d4:16 }`.
- Marks: `->` accent, `-.` staccato, `--` tenuto, `\fermata`, `\breath`, `\caesura`; dynamics `\p` `\mf`; hairpins `\<` `\>` `\!`;
  pedal `\ped` `\pedx` `\unped`; `\trl` … `\trx` trill line; `\trem3` tremolo; `\gl"wavy"` … `\glstop`; `\clef"treble"`;
  fingering `#"1"`; text `^"above"` and `_"below"`.
- Bar header: `m [page|sys] [time=6/8] [ts=hide] [mm=q=56|h.=96] [tempo="a tempo"] [reh="Var. VI Coro"] [bar=double]`.
  Senza-misura bars use `time=N/4 ts=hide`.
- Mark uncertain readings with a trailing `#?` comment.

## Tip: the last part is a fugue (use theme matching)
The closing section is a fugue. Identify the subject and countersubject on the first clean statement, then use every
later entry (transposed, possibly inverted or in stretto) to cross-check and fill in uncertain pitches, accidentals and rhythms:
copy the intervals/rhythm from the clear statement and verify against the scan. Do the same for repeated accompaniment
figures and ostinati. Mark anything resolved this way with a short comment.

## Final QA still to do
- Re-render the whole score and check every page against the scan: ties that span several bars, missing slur ends,
  clefs, time-signature changes, tempos/fermatas (these matter for the click track), and the `#?` items.
- Update `README`/`docs/FINDINGS.md`, then import the result into Dorico.
