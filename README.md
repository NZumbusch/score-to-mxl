# score-to-mxl

Toolchain + transcription that turns a scanned score (here: Jan Bach, *Concert Variations* for euphonium and piano)
into MusicXML (`.mxl`) that Dorico can import.

* `output/Concert_Variations.mxl` / `.musicxml` – the current result (rebuild with `./build.sh`).
* `transcription/*.smx` – the hand-checked transcription in a compact text notation (`docs/NOTATION.md` is the cheat-sheet inside `docs/HANDOFF.md`).
* `tools/` – page splitter, staff/notehead finders, barline detector, Audiveris wrapper, SMX→MusicXML converter, renderer, QA.
* `docs/FINDINGS.md` – what worked / didn't. `docs/HANDOFF.md` – how to continue and what is still open.

## Status (see docs/STATUS.md for the page-by-page table)
All 29 pages are in. Pages 1-20 were transcribed and checked against the scan. Pages 21-24 are good for the euphonium
and structure; their piano passages have flagged `#?` spots. Pages 25-27 and 29 are first-pass drafts
(`#? DRAFT`: correct bar count/metre/rhythm skeleton, pitches from OMR) and page 28 is a rest placeholder.
