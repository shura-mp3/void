#!/usr/bin/env bash
# VOID — `void stop` (see: bin/void help). Arguments are passed through.
exec "$(dirname "$(readlink -f "$0")")/../bin/void" stop "$@"
