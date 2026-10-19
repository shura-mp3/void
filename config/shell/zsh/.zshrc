# VOID layer for zsh (ZDOTDIR points here only inside VOID Konsole sessions). Your own rc comes first.
ZDOTDIR="${VOID_USER_ZDOTDIR:-$HOME}"
[ -f "$ZDOTDIR/.zshrc" ] && . "$ZDOTDIR/.zshrc"
. "$VOID_HOME/config/shell/void-common.sh"
if [ "${VOID_PROMPT:-1}" = 1 ] && [ -z "${STARSHIP_SHELL:-}" ] && [ -z "${POSH_THEME:-}" ]; then
    setopt PROMPT_SUBST
    __void_branch() { git symbolic-ref --short HEAD 2>/dev/null | sed 's/.*/ ⟨&⟩/'; }
    PROMPT=$'\n%F{#F2F2F2}▌%f %F{#E5E5E5}%n%F{#777777} ─ %F{#E5E5E5}%~%F{#777777}$(__void_branch)%(?..%F{#F2F2F2} ✗ %?)%f\n%F{#777777}❯%f '
fi
