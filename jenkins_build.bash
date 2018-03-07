#!/bin/bash -ex

# run tests unless --no-test is specified
RUN_TESTS=1
for i in "$@"; do
    case $i in
        --no-test)
            RUN_TESTS=0
            ;;
        *)
            ;;
    esac
done

REPO_NEWTON=$WORKSPACE
export STAGE=$WORKSPACE/stage

pushd $WORKSPACE
. ./buildenv.bash
popd

pathAppendIfMissing DYLD_LIBRARY_PATH $PARASOLID/base/shared_object

if isUbuntu; then
    export DISPLAY=:0
    export ENABLE_THUMBNAIL_SERVICE=1
fi

export PROJECT_CACHE_DIR=~/${JOB_NAME}.gradle-project-cache

# Run extra unit test to verify SBT source and previous-templates are same
export JENKINS_BUILD=true

export

rm -rf graphics
cleanEverything
cleanNodeModules
rm -rf $REPO_NEWTON/ios

if [ -e ${WORKSPACE}/ios ]; then
    rm -rf ${WORKSPACE}/ios
fi

startTime=$(date +%s)

if [ $RUN_TESTS -eq 1 ]; then
    # Include all tasks run by precommit on at least one platform. In general, unit tests should be run on all platforms, but static tests
    # only need to be run on one platform.
    ./gradlew --refresh-dependencies --info --no-daemon --project-cache-dir ${PROJECT_CACHE_DIR} --continue zookeeperClean mongoDropAll checkTidy all \
              codeChecker packageAll validateJsonMaster runCppUnitTests runJavascriptUnitTests :java:test:runAllFastTests runBasicRetrievalTest       \
              :js:verifyApiDoc :cpp:checkCppHeaderIncludes :drawing:checkCppHeaderIncludes                                                            \
              smokeTest :java:test:runExtendedRetrievalTest
else
    ./gradlew --refresh-dependencies --info --no-daemon --project-cache-dir ${PROJECT_CACHE_DIR} --continue zookeeperClean mongoDropAll packageAll
fi

$REPO_NEWTON/buildSrc/jenkins/process_corefiles.bash ${startTime} || true

# can't do killServices here because we might be running more tests. Make sure to do in the jenkins job.

