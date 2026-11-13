#!/usr/bin/env bash
# Source this before running the pipeline from a fresh shell:
#     source scripts/env.sh
#
# It only touches PATH / caches; nothing is installed.
if [ -n "${ZSH_VERSION:-}" ]; then
    _MUSIC_TRANSLATOR_ENV_FILE="${(%):-%x}"
else
    _MUSIC_TRANSLATOR_ENV_FILE="${BASH_SOURCE[0]}"
fi
_MUSIC_TRANSLATOR_ROOT="$(cd "$(dirname "$_MUSIC_TRANSLATOR_ENV_FILE")/.." && pwd)"
_WORKSPACE="$(cd "$_MUSIC_TRANSLATOR_ROOT/.." && pwd)"

if [ -z "${AUDIVERIS_EXE_PATH:-}${AUDIVERIS_PATH:-}" ] && \
   [ -x "$_WORKSPACE/.toolchain/audiveris/Audiveris.app/Contents/MacOS/Audiveris" ]; then
    export AUDIVERIS_EXE_PATH="$_WORKSPACE/.toolchain/audiveris/Audiveris.app/Contents/MacOS/Audiveris"
fi

# Bundled LilyPond 2.26 arm64 (see docs/macos_setup.md §3)
if [ -z "${LILYPOND:-}" ] && [ -x "$_WORKSPACE/.toolchain/lilypond/bin/lilypond" ]; then
    export LILYPOND="$_WORKSPACE/.toolchain/lilypond/bin/lilypond"
fi
if [ -n "${LILYPOND:-}" ]; then
    _MUSIC_TRANSLATOR_LILY_BIN="$(dirname "$LILYPOND")"
    case ":$PATH:" in
        *":$_MUSIC_TRANSLATOR_LILY_BIN:"*) ;;
        *) export PATH="$_MUSIC_TRANSLATOR_LILY_BIN:$PATH" ;;
    esac
else
    echo "warn: bundled LilyPond not found at $_WORKSPACE/.toolchain/lilypond/bin" >&2
    echo "      install it per docs/macos_setup.md §3, or export LILYPOND=/path/to/lilypond" >&2
fi

# fontconfig insists on a writable cache; keep it inside the workspace
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$_WORKSPACE/.cache/xdg}"
mkdir -p "$XDG_CACHE_HOME" 2>/dev/null || true

# venv
if [ -f "$_MUSIC_TRANSLATOR_ROOT/.venv/bin/activate" ]; then
    . "$_MUSIC_TRANSLATOR_ROOT/.venv/bin/activate"
elif [ -f "$_WORKSPACE/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    . "$_WORKSPACE/.venv/bin/activate"
else
    echo "warn: no venv at $_WORKSPACE/.venv (see docs/macos_setup.md §1)" >&2
fi

export MUSIC_TRANSLATOR_ROOT="$_MUSIC_TRANSLATOR_ROOT"
echo "music_translator env ready: python=$(command -v python 2>/dev/null || echo '?') lilypond=${LILYPOND:-not found}"
