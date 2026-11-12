#!/usr/bin/env bash
# Render sampel resmi (9:16, TTS, QC loudness). Tidak mem-publish.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src
export DRY_RUN=true
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  PY=python3
fi
exec "$PY" -m reels_autopilot sample --out "$ROOT/samples/sample_reel.mp4"
