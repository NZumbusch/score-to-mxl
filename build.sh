#!/usr/bin/env bash
# Build the Dorico-importable score from the transcription.
set -e
cd "$(dirname "$0")"
mkdir -p output
python3 tools/dsl2mxl.py transcription/00_header.smx transcription/p[0-9][0-9].smx \
    -o output/Concert_Variations.musicxml --mxl output/Concert_Variations.mxl
# review copy: uncertain (#?) passages in red, labelled with their number from docs/open_items.csv
python3 tools/dsl2mxl.py transcription/00_header.smx transcription/p[0-9][0-9].smx --mark-uncertain \
    -o output/Concert_Variations_REVIEW.musicxml --mxl output/Concert_Variations_REVIEW.mxl 2>/dev/null
