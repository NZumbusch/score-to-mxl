# score-to-mxl

Toolchain + transcription that turns a scanned score (here: Jan Bach, *Concert Variations* for euphonium and piano)
into MusicXML (`.mxl`) that Dorico can import.

* `output/Concert_Variations.mxl` / `.musicxml` – the current result (rebuild with `./build.sh`).
* `transcription/*.smx` – the hand-checked transcription in a compact text notation (`docs/NOTATION.md` is the cheat-sheet inside `docs/HANDOFF.md`).
* `tools/` – page splitter, staff/notehead finders, barline detector, Audiveris wrapper, SMX→MusicXML converter, renderer, QA.
* `docs/FINDINGS.md` – what worked / didn't. `docs/HANDOFF.md` – how to continue and what is still open.

## Status (see docs/STATUS.md for the page-by-page table)
All 29 pages are transcribed from the scan (pages 22–29 re-read in the latest pass). Remaining uncertain spots, mainly page 21 piano and some dense fugue chords, are marked `#?`.
