#!/bin/bash
set -xeou pipefail
TARGDIR=${1}
invwarp_out=${2}
ATLAS=${3}
ATLASB=${4}
ATLASBM=${5}
SESST=${6}

# Upstream iProc swapped dims here for HCP convention; for our BIDS data
# fslreorient2std has already standardized to RAS+, so swapping again
# rotates the head 90° into a non-RAS orientation that FNIRT can't align
# to MNI152 (NEWMAT::SingularException).  Just copy through.
cp ${TARGDIR}/mpr_reorient_brain.nii.gz ${TARGDIR}/mpr_brain.nii.gz

# Narrow the FLIRT search range.  -180 180 across all three axes searches
# the entire rotation space, which finds bad local optima even when the
# input is already RAS-aligned (as ours is after fslreorient2std).
# +-30 degrees is plenty for properly-oriented T1s.
flirt -in ${TARGDIR}/mpr_brain -ref ${ATLASB} -out ${TARGDIR}/mpr_brain_mni -omat ${TARGDIR}/mpr_brain_to_mni.mat -bins 256 -cost corratio -searchrx -30 30 -searchry -30 30 -searchrz -30 30 -dof 12 -interp trilinear

# FLIRT 5.0.10 in our container writes the affine in C99 hex-float format
# (e.g. 0x1.1abd7749c1773p+0).  The rest of FSL (fnirt, convertwarp,
# convert_xfm, applywarp) parses this as 0.0, producing all-zero matrices
# and NEWMAT::SingularException downstream.  Post-process to canonical
# decimal so every downstream tool can read the affine.
python3 -c "
import sys
with open('${TARGDIR}/mpr_brain_to_mni.mat') as f:
    rows = [[float.fromhex(t) for t in line.split()] for line in f if line.strip()]
with open('${TARGDIR}/mpr_brain_to_mni.mat', 'w') as f:
    for row in rows:
        f.write(' '.join(f'{v:.10f}' for v in row) + '\n')
"

# Nonlinear T1 -> MNI registration via FNIRT.  Uses FSL's standard config
# (T1_2_MNI152_2mm.cnf) tuned for this exact registration.  Now that the
# FLIRT affine is in decimal (see hex->decimal post-processing above),
# FNIRT can parse it correctly.
fnirt --in=${TARGDIR}/mpr --iout=${TARGDIR}/anat_mni_underlay --ref=${ATLAS} --refmask=${ATLASBM} --aff=${TARGDIR}/mpr_brain_to_mni.mat --cout=${TARGDIR}/mpr_to_mni_FNIRT.mat --config=T1_2_MNI152_2mm

invwarp -w ${TARGDIR}/mpr_to_mni_FNIRT.mat.nii.gz -o ${invwarp_out} -r ${TARGDIR}/mpr

# This is applying the non-brain extracted T1w to MNI warp (computed above) to 
# the brain extracted T1w, then binarizing to create a T1w to MNI brain mask
inname1=${TARGDIR}/${SESST}_mpr_brain 
outname1=${TARGDIR}/anat_mni_underlay_brain
outname2=${TARGDIR}/anat_mni_underlay_brain_mask

applywarp --ref=${TARGDIR}/anat_mni_underlay.nii.gz --in=${inname1} --warp=${TARGDIR}/mpr_to_mni_FNIRT.mat.nii.gz --rel --out=${outname1}

fslmaths ${outname1} -bin ${outname2}
