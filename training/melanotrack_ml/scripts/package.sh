#!/bin/bash
# Bundle code + results (no datasets, weights or caches) for submission.
set -e
cd /home/claude
OUT=/home/claude/docs_w579/MelanoTrack_Week5-7-9_code_and_results.zip
rm -f "$OUT"
zip -qr "$OUT" melanotrack_ml/README.md melanotrack_ml/src melanotrack_ml/scripts \
  melanotrack_ml/results -x "*/__pycache__/*" "*.pkl" "*/seg_preds.npz"
unzip -l "$OUT" | tail -1
