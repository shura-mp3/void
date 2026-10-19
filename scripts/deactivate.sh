#!/usr/bin/env bash
# VOID — `void deactivate` (see: bin/void help). Arguments are passed through.
exec "$(dirname "$(readlink -f "$0")")/../bin/void" deactivate "$@"
