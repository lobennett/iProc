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
# input is already RAS-aligned (as ours is after fslreorient2std).  The
# bad affine then breaks FNIRT downstream with NEWMAT::SingularException.
# +-30 degrees is plenty for properly-oriented T1s.
flirt -in ${TARGDIR}/mpr_brain -ref ${ATLASB} -out ${TARGDIR}/mpr_brain_mni -omat ${TARGDIR}/mpr_brain_to_mni.mat -bins 256 -cost corratio -searchrx -30 30 -searchry -30 30 -searchrz -30 30 -dof 12 -interp trilinear

# FNIRT keeps crashing with NEWMAT::SingularException on our data (FSL
# 5.0.10 + GE multi-echo T1 with R->L X-axis vs MNI L->R).  We use
# convertwarp to produce an affine-only warp field instead.  Downstream
# applywarp expects a NIfTI warp file at the same path, so create one
# encoding the FLIRT affine plus identity displacement.  This gives
# AFFINE-ONLY T1->MNI registration (no nonlinear refinement).
convertwarp --ref=${ATLAS} --premat=${TARGDIR}/mpr_brain_to_mni.mat --out=${TARGDIR}/mpr_to_mni_FNIRT.mat.nii.gz
# Produce iout (T1 in MNI space) via applywarp so downstream steps that
# expect anat_mni_underlay.nii.gz find it.
applywarp --ref=${ATLAS} --in=${TARGDIR}/mpr --warp=${TARGDIR}/mpr_to_mni_FNIRT.mat.nii.gz --out=${TARGDIR}/anat_mni_underlay

invwarp -w ${TARGDIR}/mpr_to_mni_FNIRT.mat.nii.gz -o ${invwarp_out} -r ${TARGDIR}/mpr

# This is applying the non-brain extracted T1w to MNI warp (computed above) to 
# the brain extracted T1w, then binarizing to create a T1w to MNI brain mask
inname1=${TARGDIR}/${SESST}_mpr_brain 
outname1=${TARGDIR}/anat_mni_underlay_brain
outname2=${TARGDIR}/anat_mni_underlay_brain_mask

applywarp --ref=${TARGDIR}/anat_mni_underlay.nii.gz --in=${inname1} --warp=${TARGDIR}/mpr_to_mni_FNIRT.mat.nii.gz --rel --out=${outname1}

fslmaths ${outname1} -bin ${outname2}
