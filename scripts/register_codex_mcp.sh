#!/usr/bin/env bash
set -eo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo/scripts/env.sh"
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo '请先按 docs/macos_setup.md 配置 Python 虚拟环境。' >&2
    exit 1
fi
if ! python -c 'import mcp.server.fastmcp' >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "$(command -v python)" 'mcp==1.30.0'
    else
        python -m pip install 'mcp==1.30.0'
    fi
fi
codex mcp add music-translator -- /bin/bash "$repo/scripts/run_score_review_mcp.sh"
