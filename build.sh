#!/usr/bin/env bash
# Build the Dorico-importable score from the transcription.
set -e
cd "$(dirname "$0")"
mkdir -p output
python3 tools/dsl2mxl.py transcription/00_header.smx transcription/p[0-9][0-9].smx \
    -o output/Concert_Variations.musicxml --mxl output/Concert_Variations.mxl
