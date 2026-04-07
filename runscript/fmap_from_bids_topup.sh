#!/bin/bash
set -xeou
#Apply fieldmap correction # iProc_fm.sh 4GP28 170712_HTP02020 33 34 /ncf/cnl03/25/users/DN2/fm_test

# echo every line to stdout as it runs, and exit if any command returns nonzero,
# even if there is a pipe
AP_BIDS_NIFTI=$1
PA_BIDS_NIFTI=$2
FDIR=$3
codedir=$4
TotalReadoutTime=$5
outfile=$6 #this now is without the .nii.gz to acoomodate a masked version for QC 2025.06.11 JS
OUTDIR=$7
MASK_COPY=$8 # added by LMD

preptool=topup

# symlink BIDS NIFTI files to the expected locations ${FDIR}/AP_img.nii.gz and ${FDIR}/PA_img.nii.gz
ln -sf "${AP_BIDS_NIFTI}" "${FDIR}/AP_img.nii.gz"
ln -sf "${PA_BIDS_NIFTI}" "${FDIR}/PA_img.nii.gz"

# change later if it comes up
b02b0=$codedir/configs/b02b0.cnf

pushd $FDIR

# compute and write dicom info
datain=$FDIR/topupDatain.dat
# in case there is already such a file, overwrite it
rm -f $datain


# Add If statement for topup if AP order scans AP/PA if PA order scans PA/AP
if [[ $OUTDIR == *_AP ]]
    then echo FMAP order for topup: AP is first, PA is second
    echo "0 -1 0 $TotalReadoutTime" >> $datain
    echo "0 1 0 $TotalReadoutTime" >> $datain
elif [[ $OUTDIR == *_PA ]]
    then echo FMAP order for topup: PA is first, AP is second
    echo "0 1 0 $TotalReadoutTime" >> $datain
    echo "0 -1 0 $TotalReadoutTime" >> $datain
fi
echo $OUTDIR does not contain AP or PA

#echo "0 -1 0 $TotalReadoutTime" >> $datain
#echo "0 1 0 $TotalReadoutTime" >> $datain

# we're assuming that the PA and AP files have all the same scan parameters here, e.g. TotalReadoutTime
${codedir}/runscript/fmap_${preptool}_prep.sh ${FDIR} ${outfile} ${datain} ${b02b0} ${OUTDIR} ${MASK_COPY} ## this currently must only work with fmap_topup_prep.sh - LMD

