#!/bin/bash
set -xeou pipefail
# Fieldmap prep script, originally from fm.sh.
# separated from xnat download for modularity.
FDIR=$1
outfile=$2 #Wihtout .nii.gz extension for QC masked version 2025.06.11 JS
datain=$3
b02b0=$4
OUTDIR=$5
MASK_COPY=$6 # added for FMAP QC

# needed for the best version of topup
if module load fsl/6.0.1-ncf 2>/dev/null; then
    echo "Loaded fsl/6.0.1-ncf via module"
elif [ -n "${FSLDIR:-}" ]; then
    echo "Using FSL from FSLDIR: $FSLDIR"
else
    echo "ERROR: FSL not available via module or FSLDIR" >&2
    exit 1
fi

cd $FDIR

# copped from HCP. Check that the two unwarp images are the same size.
test "$(fslhd PA_img.nii.gz | grep '^dim[123]')" == "$(fslhd AP_img.nii.gz | grep '^dim[123]')"

# If statement added for topup: If AP order scans AP/PA if PA order scans PA/AP
# This statement is dependent on output directory structure: Must have "AP" or "PA" in the name.
# # Option to add in logging error echo $OUTDIR does not contain AP or PA
if [[ $OUTDIR == *_AP ]]
    then echo FMAP order for topup: AP is first, PA is second
    fslmerge -t all_images.nii.gz AP_img.nii.gz PA_img.nii.gz
elif [[ $OUTDIR == *_PA ]]
    then echo FMAP order for topup: PA is first, AP is second
    fslmerge -t all_images.nii.gz PA_img.nii.gz AP_img.nii.gz
fi

topup --imain=all_images.nii.gz --datain=$3 --config=$b02b0 --fout=topup_fmap.nii.gz --iout=se_epi_unwarped.nii.gz --out=topup_out

#convert to radians by miltiplying by 2pi
fslmaths topup_fmap.nii.gz -mul 6.28 ${outfile}.nii.gz

#create magniture image and bet it
fslmaths se_epi_unwarped.nii.gz -Tmean mag_img.nii.gz
bet2 mag_img.nii.gz mag_img_brain.nii.gz -m -g 0.1 -f 0.45
fslmaths $FDIR/mag_img_brain -ero $FDIR/mag_img_brain_ero
cp mag_img_brain_mask.nii.gz $MASK_COPY 

#for QC
fslmaths ${outfile}.nii.gz -mas $MASK_COPY ${outfile}_masked.nii.gz
