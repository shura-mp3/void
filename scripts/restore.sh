#!/usr/bin/env bash
# VOID — `void restore` (see: bin/void help). Arguments are passed through.
exec "$(dirname "$(readlink -f "$0")")/../bin/void" restore "$@"
