#!/usr/bin/env bash
# Grouped conversion uses the same Python environment as batch.py.
set -e
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python "$script_dir/run_batch_20.py" "$@"
