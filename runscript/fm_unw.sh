#!/bin/bash
set -xeou pipefail
#Apply fieldmap correction
# R.Braga Feb 2018

# ./fm_unw_midvol.sh 4GP28 170712_HTP02020 014 PAIN /ncf/cnl03/25/users/DN2/data /ncf/cnl03/25/users/DN2/data/4GP28/cross_session_maps/templates/4GP28_D01_REST1_midvol

FM_SESS=$1
FDIR=$2
IMG=$3
OUTFILE=$4
FM_BOLDNO=$5
DDIR=$6
OUTPUT_WARP_DIR=$7
unwarp_direction=$8
ME=$9
#rmfiles=${10:-''}

echo rmfiles

echo "unwarp direction is ${unwarp_direction}"

# # # # 
mkdir -m 750 -p $OUTPUT_WARP_DIR
pushd $OUTPUT_WARP_DIR

fslmaths $IMG example_func
fslmaths $IMG prefiltered_func_data

fmap=$FDIR/${FM_SESS}_${FM_BOLDNO}_fieldmap 
mag_img=$FDIR/mag_img

# The HCP-derived dim check was too strict: GE acquisitions often have fmap
# and BOLD at different in-plane resolution (e.g. 128x128x60 fmap vs 80x80x51
# BOLD).  The FLIRT step below (line ~77) resamples the fmap into BOLD space
# via the linear transform, so equal dimensions are not required for the math.
# Keep a warning instead of a hard fail.
if [[ "$(fslhd $mag_img | grep '^dim[123]')" != "$(fslhd $IMG | grep '^dim[123]')" ]]; then
    echo "INFO: fmap mag_img and BOLD reference have different dims; FLIRT will resample."
fi

fslmaths $fmap FM_UD_fmap
fslmaths ${mag_img} FM_UD_fmap_mag
fslmaths ${mag_img}_brain FM_UD_fmap_mag_brain
fslmaths ${mag_img}_brain_mask FM_UD_fmap_mag_brain_mask 

# get echo time for image
IMGDIR=$(dirname $IMG)
IMG_BOLDNO=$(echo $IMG | egrep -o 'bld[[:digit:]]{3}')
pushd $IMGDIR
# temporary workaround for when there are multiple scans in same directory. 
#If they're the same task this value should be the same anyway.
echo $ME
if [ "$ME" = "1" ]; then
	echo " ----- IN fm_unw.sh: IS MULTIECHO -----"
	echo_time=$(cat *${IMG_BOLDNO}*echoTime_e1.sec)
	dwelltime=$(cat *${IMG_BOLDNO}*dwellTime_e1.sec)
else
	echo_time=$(cat *${IMG_BOLDNO}*echoTime.sec)
	dwelltime=$(cat *${IMG_BOLDNO}*dwellTime.sec)
fi

popd

fslmaths FM_UD_fmap -sub `fslstats FM_UD_fmap -k FM_UD_fmap_mag_brain_mask -P 50` FM_UD_fmap

fslmaths FM_UD_fmap -sub `fslstats FM_UD_fmap -R | awk '{ print  $1}'` -add 10 -mas FM_UD_fmap_mag_brain_mask grot

fslstats grot -l 1 -p 0.1 -p 95

# echo time was originally fixed at 0.0326
#TODO: echo time for double echo: what is
sigloss -i FM_UD_fmap --te=$echo_time -m FM_UD_fmap_mag_brain_mask -s FM_UD_fmap_sigloss

fslmaths FM_UD_fmap_sigloss -mul FM_UD_fmap_mag_brain FM_UD_fmap_mag_brain_siglossed -odt float

fugue -i FM_UD_fmap_mag_brain_siglossed --loadfmap=FM_UD_fmap --mask=FM_UD_fmap_mag_brain_mask --dwell=$dwelltime -w FM_D_fmap_mag_brain_siglossed --nokspace --unwarpdir=$unwarp_direction

fugue -i FM_UD_fmap_sigloss --loadfmap=FM_UD_fmap --mask=FM_UD_fmap_mag_brain_mask --dwell=$dwelltime -w FM_D_fmap_sigloss --nokspace --unwarpdir=$unwarp_direction

fslmaths FM_D_fmap_sigloss -thr 0.9 FM_D_fmap_sigloss

flirt -in example_func -ref FM_D_fmap_mag_brain_siglossed -omat EF_2_FM.mat -o grot -dof 6 -refweight FM_D_fmap_sigloss

convert_xfm -omat FM_2_EF.mat -inverse EF_2_FM.mat

flirt -in FM_UD_fmap -ref example_func -init FM_2_EF.mat -applyxfm -out EF_UD_fmap

flirt -in FM_UD_fmap_mag_brain -ref example_func -init FM_2_EF.mat -applyxfm -out EF_UD_fmap_mag_brain

flirt -in FM_UD_fmap_mag_brain_mask -ref example_func -init FM_2_EF.mat -applyxfm -out EF_UD_fmap_mag_brain_mask

fslmaths FM_UD_fmap_mag_brain_mask -thr 0.5 -bin FM_UD_fmap_mag_brain_mask -odt float

fugue --loadfmap=EF_UD_fmap --dwell=$dwelltime --mask=EF_UD_fmap_mag_brain_mask -i example_func -u UD_example_func --unwarpdir=$unwarp_direction --saveshift=EF_UD_shift

convertwarp -s EF_UD_shift -o EF_UD_warp -r example_func --shiftdir=$unwarp_direction

# perhaps prefiltered_func_data and example_func need to be different here. Not changing what isn't broken.
applywarp -i prefiltered_func_data -o prefiltered_func_data_unwarp -w EF_UD_warp -r example_func --abs --mask=EF_UD_fmap_mag_brain_mask

fslmaths prefiltered_func_data_unwarp ${OUTFILE}

popd

#if [ -n "$rmfiles" ]; then
#    for f in $rmfiles;do
#        rm -rf "$f"
#    done
#fi
