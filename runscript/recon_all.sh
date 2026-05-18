#!/bin/bash
set -xeou pipefail
#
#Usage: iProc_fs.sh <subjid> <scan_no> <anat_scan_no> <subjects_dir> <basedir> <codedir>
# e.g.  iProc_fs.sh 5MQ58 170710_HTP02017 010 

# Written by R. Braga - Feb 2018

SUBJECT=$1
fs_sub=$2
MPR_REORIENT=$3
T2_REORIENT=$4
SUBJECTSDIR=$5
FSAVERAGE6=$6
SCRATCHDIR=$7
CODEDIR=$8

cpus=$(python -c "import os; cpus=len(os.sched_getaffinity(0)); print(cpus)")
export OMP_NUM_THREADS=${cpus}

origdir=$SCRATCHDIR/$SUBJECT/${fs_sub}/mri/orig
if [ -d "$origdir" ]; then 
    rm -Rf $origdir 
fi

mkdir -m 750 -p $origdir

mri_convert $MPR_REORIENT $origdir/001.mgz
input_file=$origdir/001.mgz

if [ "${T2_REORIENT}" != "__none__" ]; then
    recon-all \
        -sd $SCRATCHDIR/${SUBJECT} \
        -s ${fs_sub} \
        -T2 ${T2_REORIENT} \
        -all \
        -custom-tal-atlas RLB700_atlas_as_orig \
        -parallel \
        -openmp $OMP_NUM_THREADS
else
    recon-all \
        -sd $SCRATCHDIR/${SUBJECT} \
        -s ${fs_sub} \
        -all \
        -custom-tal-atlas RLB700_atlas_as_orig \
        -parallel \
        -openmp $OMP_NUM_THREADS
fi

sleep 3

echo "Moving /scratch/${SUBJECT}/${fs_sub}/ contents to ${SUBJECTSDIR}/${fs_sub}/"
mkdir -p ${SUBJECTSDIR}/${fs_sub}/
# rsync is not in the container; use mv (same filesystem, instant rename, no copy).
mv $SCRATCHDIR/${SUBJECT}/${fs_sub}/* ${SUBJECTSDIR}/${fs_sub}/

ln -sfT ${FSAVERAGE6} $SUBJECTSDIR/fsaverage6
