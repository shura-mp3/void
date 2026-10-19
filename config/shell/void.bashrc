# VOID layer for bash (loaded with --rcfile by bin/void-shell). Your ~/.bashrc comes first.
[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"
. "$VOID_HOME/config/shell/void-common.sh"

# Monochrome prompt. Kept off when you use starship/oh-my-posh, or with VOID_PROMPT=0.
if [ "${VOID_PROMPT:-1}" = 1 ] && [ -z "${STARSHIP_SHELL:-}" ] && [ -z "${POSH_THEME:-}" ]; then
    __void_ps1() {
        local s=$? b
        b=$(git symbolic-ref --short HEAD 2>/dev/null)
        local m='\[\e[38;2;119;119;119m\]' t='\[\e[38;2;229;229;229m\]' w='\[\e[38;2;242;242;242m\]' z='\[\e[0m\]'
        PS1="\n${w}▌${z} ${t}\u${m} ─ ${t}\w${b:+${m} ⟨${b}⟩}"
        [ $s -ne 0 ] && PS1+="${w} ✗ ${s}"
        PS1+="${z}\n${m}❯${z} "
    }
    PROMPT_COMMAND="__void_ps1${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi
