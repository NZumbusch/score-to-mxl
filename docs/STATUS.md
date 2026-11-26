# Page-by-page status

| Pages | State | Notes |
|---|---|---|
| 1–20 | transcribed + proof-read against the scan | ~40 small `#?` items (grep for it) |
| 21 | euphonium good; piano arpeggios/Coro chords approximate | 19 `#?` — the main remaining weak spot |
| 22 | re-read from the scan: rhythms/bar lengths fixed (unprinted 5/4, 2/4, 2/4 bars in the recit.), piano chords read | 11 `#?` (semplice runs, LH treble dyads) |
| 23 | re-read: octave lines now at sounding pitch, fugue subject with 32nd turns, piano | 4 `#?` |
| 24–29 | transcribed bar by bar from the scan (28 was a placeholder, 25–27/29 were OMR drafts), cross-checked with fugue subject entries, canons and repeated figures | dense chord spellings flagged `#?` (2–15 per page) |

All 366 bars build without bar-length warnings.

## Checks done
- Every page 22–29 rendered (`tools/render.py`) and compared with the scan.
- Converter: `\sff`/`\ffp` were silently dropped (fixed), unknown commands now warn, ties held into a later chord are kept,
  phrase slurs left open are closed before the next slur instead of being dropped (end on the note where a tie starts).
- Remaining build warnings: 22 dropped ties (mostly page 21/22 approximations and ties before rests) – review with the scan.

## Open work
1. Page 21 piano (arpeggios in bar 268, Coro chord spellings) and the `#?` items: `grep -n "#?" transcription/*.smx`.
2. Import into Dorico; confirm tempo track and hide-empty-staves for the 3rd piano staff.
