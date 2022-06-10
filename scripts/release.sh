#!/bin/sh -x
DIRNAME="$(dirname "$0")"

# set PROJECT_NAME variable
. "$DIRNAME"/projectname.sh

# utility functions
. "$DIRNAME"/functions.sh

if ! branch_is_master;
then
    quit "Checkout branch 'master' before generating release." 1
fi

if ! branch_is_clean;
then
    echo "Tree contains uncommitted modifications:"
    git ls-files -m
    quit 1
fi
version=$(current_version);

if ! version_is_tagged "$version";
then
    echo "Current version $version isn't tagged."
    echo "Attempting to tag..."
    "$DIRNAME"/tag.sh || quit "Failed to tag a release." 1
fi

