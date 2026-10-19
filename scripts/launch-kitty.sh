#!/usr/bin/env bash
# VOID — open Kitty in VOID mode: shell (default) | lyrics | music | cava | fetch | dashboard.
# Uses your kitty.conf with VOID's void.conf on top; kitty.conf itself is never edited by this.
exec "$(dirname "$(readlink -f "$0")")/../bin/void" kitty "$@"
