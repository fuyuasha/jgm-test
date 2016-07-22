#!/bin/bash -ex

# Purpose: process new/changed l10n resources from Transifex

function mergeToCurrentBranch() {
   local commentPrefix="${1}"
   shift
   local gitBranch="${1}"
   shift
   local workBranch="${1}"
   shift
   local transListFile="${1}"
   shift
   local gitDiffRelFile="${1}"
   shift
   local tmpFilePrefix="${1}"

   local grepTmpFile="${tmpFilePrefix}grep.txt"
   local exitVal=0
   local returnVal=0

   git add -A
   git commit -m "${commentPrefix} added non-English resource changes"

   # Check that if there's any difference it's a subset of what transupdate.py downloaded
   git diff ${gitBranch} --name-only | sort > ${gitDiffRelFile}
   if [ $(cat ${gitDiffRelFile} | wc -l) -gt 0 ]; then
      # Get lines in $gitDiffRelFile that don't exist in $transListFile
      grep -F -x -v -f ${transListFile} ${gitDiffRelFile} > ${grepTmpFile}
      if [ $(cat ${grepTmpFile} | wc -l) -eq 0 ]; then
         git checkout ${gitBranch}
         ${WORKSPACE}/tools/mergepush.py ${workBranch} -m "${commentPrefix} merged non-English resource changes"
         exitVal=$?
         if [ ${exitVal} -eq 0 ]; then
            echo "Added the following new or modified resources to ${gitBranch}:"
            cat ${gitDiffRelFile}
         fi
      else
         echo "ERROR: can't mergepush ${workBranch} on ${gitBranch} because of unrecognized files:" >&2
         cat ${grepTmpFile} >&2
         exitVal=1
      fi
   else
      echo "No resource files have changed"
      returnVal=1
   fi

   git checkout master
   set +e; git branch -D ${workBranch} > /dev/null 2>&1; set -e

   if [ ${exitVal} -ne 0 ]; then exit 1; fi

   return ${returnVal}
}

function mergeToMasterBranch() {
   local commentPrefix="${1}"
   shift
   local gitBranch="${1}"
   shift
   local scriptName="${1}"
   shift
   local gitDiffRelFile="${1}"
   shift
   local tmpFilePrefix="${1}"

   local gitDiffMasterFile="${tmpFilePrefix}gitdiffmaster.txt"
   local gitDiffDiffFile="${tmpFilePrefix}gitdiffdiff.txt"
   local exitVal=0

   # Checkout a master working branch
   local mergeBackBranch=${scriptName}-master
   set +e; git branch -D $mergeBackBranch > /dev/null 2>&1; set -e
   git checkout master
   git checkout -b ${mergeBackBranch} master

   ${WORKSPACE}/tools/pullmerge.py master -m "${commentPrefix} pullmerge master into ${mergeBackBranch}"
   exitVal=$?
   if [ ${exitVal} -eq 0 ]; then
      ${WORKSPACE}/tools/pullmerge.py ${gitBranch} -m "${commentPrefix} pullmerge ${gitBranch} into ${mergeBackBranch}"
      exitVal=$?
      if [ ${exitVal} -eq 0 ]; then
         # Check for the expected difference
         git diff master --name-only | sort > ${gitDiffMasterFile}
         set +e; diff ${gitDiffMasterFile} ${gitDiffRelFile} > $gitDiffDiffFile; set -e;
         if [ $(cat ${gitDiffDiffFile} | wc -l) -eq 0 ]; then
            git checkout master
            ${WORKSPACE}/tools/mergepush.py ${mergeBackBranch} -m "${commentPrefix} mergepush ${mergeBackBranch}"
            echo "Merged resources to master"
         else
            echo "ERROR: can't mergepush ${mergeBackBranch} on master - unexpected differences:" >&2
            cat ${gitDiffDiffFile} >&2
            exitVal=1
         fi
      fi
   fi

   git checkout master
   set +e; git branch -D ${mergeBackBranch} > /dev/null 2>&1; set -e

   if [ ${exitVal} -ne 0 ]; then exit 1; fi
}

# Main

scriptFileName=${0##*/}
scriptName=${scriptFileName%.*}

if [ -z "$1" ]; then
    echo "Usage: $scriptName <Onshape repository name>"
    echo "   ex: $scriptName ios"
    exit 1
fi
transProjName="$1"

if [ -z "$WORKSPACE" ]; then
    echo "WORKSPACE must be set to the repo clone folder."
    exit 1
fi

. ${WORKSPACE}/tools/git.bash

# Variables with defaults and overrides (for testing)
[ -z "$OVERRIDE_GITBRANCH" ] && gitBranch="$(getGitBranch)" || gitBranch=${OVERRIDE_GITBRANCH}
[ -z "$OVERRIDE_PYTHON_CMD" ] && pythonCmd="~/virtualenv/onshape-python-transifex/bin/python" || pythonCmd=${OVERRIDE_PYTHON_CMD}
[ -z "$OVERRIDE_CLONEPATH" ] && clonePath="${WORKSPACE}" || clonePath=${OVERRIDE_CLONEPATH}

tmpFilePrefix="/tmp/${scriptName}-${transProjName}-"
rm -f ${tmpFilePrefix}* > /dev/null 2>&1

transListFile="${tmpFilePrefix}trans.txt"
gitDiffRelFile="${tmpFilePrefix}gitdiffrel.txt"
commentPrefix="[auto] $scriptName -"

# Get the current branch
gitBranch=${gitBranch//origin-/}

# Checkout a current working branch
workBranch=${scriptName}-${gitBranch}
set +e; git branch -D ${workBranch} > /dev/null 2>&1; set -e
git checkout ${gitBranch}
git checkout -b ${workBranch} ${gitBranch}

# Download the latest non-English resources from Transifex
eval ${pythonCmd} ${WORKSPACE}/tools/transupdate.py -m down -dlf ${transListFile} -ckf ~/.transifex -gb ${gitBranch} -rn ${transProjName} -c ${clonePath} -rl localize.json -tc ~/.transifex.json
# NOTE: transupdate.py uses exit code 1 (and only this) for failure and other non-zero exit codes to denote alternate successful outcomes
[ $? -eq 1 ] && exit 1
printf "\n"

# Mergepush any new or changed resources to current branch then master
if mergeToCurrentBranch "${commentPrefix}" "${gitBranch}" "${workBranch}" "${transListFile}" "${gitDiffRelFile}" "${tmpFilePrefix}"; then
   # gitBranch is normally the latest "rel" branch (but exceptionally could be "master")
   if [ "${gitBranch}" != "master" ]; then
      mergeToMasterBranch "${commentPrefix}" "${gitBranch}" "${scriptName}" "${gitDiffRelFile}" "${tmpFilePrefix}"
   fi
fi
