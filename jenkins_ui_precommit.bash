#!/bin/bash -ex

if [ $# -ne 1 ]; then
    echo "Usage: $0 remote-address"
    exit 1
fi

targetUrl=$1

REPO_NEWTON=$WORKSPACE
export STAGE=$WORKSPACE/stage
export DISPLAY=:0

if [ -d "$STAGE/test/results" ]; then
    rm -r $STAGE/test/results > /dev/null 2>&1
fi

. ./buildenv.bash

export PROJECT_CACHE_DIR=~/${JOB_NAME}.gradle-project-cache
rm -rf $PROJECT_CACHE_DIR

./gradlew --info --no-daemon --project-cache-dir ${PROJECT_CACHE_DIR} --continue --full-stacktrace \
    :java:serializable-generator:runCodeGenForSerializables

killChrome

yarn install
./node_modules/grunt-cli/bin/grunt precommitWithProxy --target=$targetUrl --hostUrl=https://localhost.dev.onshape.com:8443

killChrome
