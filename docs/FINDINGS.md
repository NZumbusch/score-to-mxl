# Findings: converting scanned scores to MusicXML for Dorico

Notes from converting *Concert Variations* (Jan Bach, euphonium & piano; 30-page scan,
landscape pages rotated 90°, ~300 dpi).

## Pipeline

1. `tools/split_pages.py SCORE.pdf work/sys` – rasterise, rotate upright, deskew, detect
   staves (5-line groups found in several vertical strips; robust to slurs & indents) and
   systems (staves joined by a left barline/brace).
2. **Draft**: Audiveris batch OMR per page (`tools/setup_audiveris.sh`) → `.mxl`.
3. **Correct**: transcription in the SMX text format (`transcription/*.smx`, see
   `docs/NOTATION.md`), checked bar-by-bar against the scan using
   - `tools/heads.py` – notehead finder that draws pitch names on each detected head
     (staff-line removal + morphological opening + chord splitting) and a page-x ruler
     (clef changes are given as `bass>treble@1500`); `dump()` prints heads numerically.
   - `tools/view.py` – crops with an optional pitch grid.
4. `tools/dsl2mxl.py header.smx p*.smx -o score.musicxml --mxl score.mxl` – converter.
   Validates bar lengths per voice (warnings), handles tuplets (nested), graces, ties,
   slurs, cross-staff notes (`@1/@2/@3`), notehead shapes (`@dia`, `@x`, `@paren`),
   fingering stacks, dynamics/hairpins, pedal, tempo/metronome, fermatas, tremolos.
5. `tools/render.py score.musicxml outdir` – verovio render to PNG for visual comparison
   with the scan (system breaks follow the original).

## What works / doesn't

- **Audiveris** (built from source, JDK 25): good first draft for pitches and simple
  rhythms. Problems on this score: splits the piano into spurious extra parts, loses
  accidentals, wrong voice lengths in dense/cross-staff passages, no understanding of
  multiphonic notation (diamond = sung, bracketed = resultant tone). Treat as a draft only.
- **Vision-only reading** (looking at crops) is unreliable for exact pitch in dense chords
  and ledger-line passages; the notehead overlay fixes most of that. Accidentals and
  merged heads a second apart still need zoomed manual checks.
- **Rhythm validation** in the converter catches many reading errors (missing tuplet
  brackets, missing dots).
- **Resultant-tone check** for multiphonics: the bracketed pitch ≈ sum of played + sung
  frequencies. Used to verify the diamond pitches (e.g. F#2 + C#3 → A#3).
- Piano is a 3-staff instrument throughout (the score switches between 2 and 3 piano
  staves). In Dorico use *Layout Options → Vertical Spacing / Staves → hide empty staves*
  so 2-stave systems look like the original.

## Environment notes

- GitHub release downloads are blocked by the session proxy; cloning works.
- Hosts needed for the Audiveris build: github.com, Maven Central, repository.jboss.org.

## Musical reasoning as a check (very effective)

- Repeating accompaniment patterns (e.g. the Siciliano piano figure: dotted-8th.. + 32nd + 8th
  chord | dotted-quarter chord) give the rhythm of dense bars; copy the pattern from a clean bar
  and only change pitches, then verify against the scan.
- The converter's per-voice bar-length check catches misread dots/flags/tuplets immediately.
- Harmony/voice leading helps resolve ambiguous accidentals (e.g. chord spelling consistent
  with the surrounding bars), but always confirm against the zoomed scan.
- Audiveris drafts are good for pitches of simple lines; their voice/rhythm assignment in
  dense piano writing is often wrong.
