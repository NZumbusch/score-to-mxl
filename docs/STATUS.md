# Page-by-page status

| Pages | State | Notes |
|---|---|---|
| 1–20 | transcribed + proof-read against the scan | a few spots marked `#?` (grep for it) |
| 21 | euphonium good; piano arpeggios/Coro chords approximate | `#?` |
| 22 | euphonium good; piano best-effort | no Audiveris draft existed |
| 23 | structure + fugue subject exact; fugue bars 2–6 euph pitches and all piano approximate | `#?` |
| 24 | euphonium read from scan and bar-sum checked; piano from draft | `#?` |
| 25, 26, 27, 29 | **DRAFT** (Audiveris pitches, bars/metre/rhythm forced to bar length) | every line ends with `#? DRAFT` |
| 28 | **PLACEHOLDER** (12 bars of 4/4 rest, rehearsal H) | transcribe from scan |

## Open work, in priority order
1. Page 28 from scratch, then the DRAFT pages 25–27, 29 (euphonium first: use the fugue subject
   `r16 g2 a2 g2 | bb2-> a2 ab2 g2 | r16 g2 an2 g2 | bb2-> a2 ab2 g2` and its transposed entries to verify pitches).
2. `grep -n "#?" transcription/*.smx` – resolve each flagged reading against the scan.
3. Final proof-read of rendered pages (`tools/render.py`) against the scan: ties/slurs/clefs/8va/pedal/dynamics.
4. `tools/qa.py` on the final file (its "beats vs" lines are partly artifacts of multi-voice padding; ties/slurs/tuplets
   sections are meaningful). The converter now drops ties without a matching continuation (78 at last build, listed
   as warnings by `./build.sh`) and unmatched slur marks (43) – review those warnings.
5. Import into Dorico; confirm tempo track (metronome marks are in the file) and hide-empty-staves for the 3rd piano staff.
