# shellcheck shell=sh
# VOID shell layer — shared by bash and zsh. Sourced by void.bashrc / zsh/.zshrc AFTER your own rc.
# Only VOID Konsole sessions load this (via bin/void-shell); nothing here is written to your dotfiles.

void() { "$VOID_HOME/bin/void" "$@"; }
alias vfetch='void fetch'
alias vmusic='void music'
alias vdash='void launch'
alias vstatus='void status'

# Geass fastfetch once per window (not in nested shells, not when disabled)
if { [ "${VOID_STARTUP_FETCH:-1}" = 1 ] || [ -n "${VOID_DASHBOARD_FETCH:-}" ]; } && [ -z "${VOID_FETCHED:-}" ]; then
    export VOID_FETCHED=1
    "$VOID_HOME/bin/void" fetch 2>/dev/null
fi
