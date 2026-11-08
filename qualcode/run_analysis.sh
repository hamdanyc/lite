#!/usr/bin/env bash
set -euo pipefail

NUM_FILES="${1:-}"

if [[ -n "${NUM_FILES}" ]]; then
  python analyze_conflict.py --max-articles "${NUM_FILES}"
else
  python analyze_conflict.py
fi
