#!/usr/bin/env bash
set -eo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
source scripts/env.sh >&2
exec python -m core.omr.review_mcp
