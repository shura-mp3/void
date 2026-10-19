# VOID: load your own ~/.zshenv (ZDOTDIR is redirected only to add VOID's layer to .zshrc)
[ -f "${VOID_USER_ZDOTDIR:-$HOME}/.zshenv" ] && . "${VOID_USER_ZDOTDIR:-$HOME}/.zshenv"
