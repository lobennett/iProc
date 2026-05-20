#!/bin/bash
set -xeou pipefail
SPLIT_IN=${1}
pyscript=${2}
MATDIR=${3}
NUMVOLS=${4}
OUTDIR=${5}
SUBID=${6}
TASK=${7}
SESSID=${8}
BOLDNO=${9}
TEMPLATE_DIR=${10}
SPACE=${11}
MNI_ATLAS=${12}
SCRATCH=${13}
rmfiles=${14:-''}

SCRATCHDIR=$(mktemp --directory --tmpdir=${SCRATCH})

pushd $SCRATCHDIR

fslsplit ${SPLIT_IN} ./time_point_

${pyscript} -m ${MATDIR} -n ${NUMVOLS} -o ${OUTDIR} -s ${SUBID} -t ${TASK} -x ${SESSID} -b ${BOLDNO} --template-dir ${TEMPLATE_DIR} --destination-space ${SPACE} --mni-atlas ${MNI_ATLAS} --scratch=$SCRATCHDIR

popd 

temp_save_dir=${OUTDIR}/${BOLDNO}_${SPACE}
old_temp_save_dir=$temp_save_dir
while [ -d $old_temp_save_dir ]
do
    old_temp_save_dir=${temp_save_dir}_$(date +%s)
done
if [ -d $temp_save_dir ];then
    mv $temp_save_dir $old_temp_save_dir
fi
mkdir $temp_save_dir
# rsync isn't in the iproc container; use mv + rmdir to mimic
# `rsync -av --remove-source-files` then cleanup the now-empty scratch dir.
mv $SCRATCHDIR/* $temp_save_dir/
rmdir $SCRATCHDIR

if [ -n "$rmfiles" ]; then
    for f in $rmfiles;do
        rm -rf "$f"
    done
fi

