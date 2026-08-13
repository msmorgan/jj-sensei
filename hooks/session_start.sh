#!/bin/sh
# SessionStart hook: inject lean jj guidance, but only inside a jj repo.
# Detect the workspace marker without running jj. Even a read-looking jj command
# can synchronize a colocated Git repository and need write access to .git.
search_dir=$(pwd -P) || exit 0
while :; do
    if [ -d "$search_dir/.jj" ]; then
        cat "$(dirname "$0")/jj-context.md"
        exit 0
    fi
    [ "$search_dir" = / ] && exit 0
    search_dir=${search_dir%/*}
    [ -n "$search_dir" ] || search_dir=/
done
