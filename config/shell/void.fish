# VOID layer for fish (sourced with -C by bin/void-shell, after your own config.fish).
function void; "$VOID_HOME/bin/void" $argv; end
alias vfetch 'void fetch'
alias vmusic 'void music'
alias vdash 'void launch'
if test "$VOID_STARTUP_FETCH" != 0; and not set -q VOID_FETCHED
    set -gx VOID_FETCHED 1
    "$VOID_HOME/bin/void" fetch 2>/dev/null
end
