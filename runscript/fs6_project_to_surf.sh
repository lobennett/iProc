#!/bin/bash
set -xeou pipefail
# Written by Rodrigo Braga - November 2017

BOLD=$1
BOLD2=$2
BOLD3=$3
SESST=$4
BOLDPATH=$5
OUTPATH=$6
scratch_base=$7
SMOOTH=$8
BOLD4=$9
SMOOTH_NAME=${SMOOTH/./p}
mkdir -p $OUTPATH

#tmpdir=$(mktemp --directory --tmpdir=${scratch_base})
tmpdir=$OUTPATH

cd $tmpdir

if [ "${IPROC_SRUN:-NO}" == "YES" ] ; then
    _IPROC_RUNNER="srun --export=ALL -n 1 -c $SLURM_CPUS_PER_TASK"
else
    _IPROC_RUNNER=""
fi

BOLDS=("$BOLD" "$BOLD2" "$BOLD3" "$BOLD4")

run_cmds() {
    if command -v parallel &>/dev/null; then
        $_IPROC_RUNNER parallel -j 4 --tmpdir=${tmpdir}
    else
        while IFS= read -r cmd; do
            bash -c "$cmd"
        done
    fi
}

#Project data
run_cmds <<EOF
$(for b in "${BOLDS[@]}"; do
    echo "mri_vol2surf --mov $BOLDPATH/${b}.nii.gz --regheader $SESST --hemi lh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/lh.${b}_fsaverage6.nii --reshape --interp trilinear"
    echo "mri_vol2surf --mov $BOLDPATH/${b}.nii.gz --regheader $SESST --hemi rh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/rh.${b}_fsaverage6.nii --reshape --interp trilinear"
done)
EOF

#Smooth data
run_cmds <<EOF
$(for b in "${BOLDS[@]}"; do
    echo "mri_surf2surf --hemi lh --s fsaverage6 --sval $tmpdir/lh.${b}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/lh.${b}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape"
    echo "mri_surf2surf --hemi rh --s fsaverage6 --sval $tmpdir/rh.${b}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/rh.${b}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape"
done)
EOF

# Gzip outputs
run_cmds <<EOF
$(for b in "${BOLDS[@]}"; do
    echo "gzip -f $tmpdir/lh.${b}_fsaverage6_sm${SMOOTH_NAME}.nii"
    echo "gzip -f $tmpdir/rh.${b}_fsaverage6_sm${SMOOTH_NAME}.nii"
    echo "gzip -f $tmpdir/lh.${b}_fsaverage6.nii"
    echo "gzip -f $tmpdir/rh.${b}_fsaverage6.nii"
done)
EOF

#rsync -av --remove-source-files ${tmpdir}/* ${OUTPATH}

echo "Output at:"
echo "$OUTPATH/lh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii.gz"
