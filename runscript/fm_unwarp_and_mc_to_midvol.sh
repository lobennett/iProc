#!/bin/bash
set -xeou pipefail

MC_IN=${1}
MC_OUT=${2}
TARGET=${3}
FLIRT_OUT=${4}
FLIRT_MAT_OUT=${5}
SCAN_TYPE=${6}
NUMVOL=${7}
OUTDIR=${8}
CODEDIR=${9}
FM_SESSID=${10}
FM_BOLDNO=${11}
MIDVOL=${12}
FMdir=${13}
REGRESSORS_MC_DAT_OUT=${14}
DEST_DIR=${15}
WARP_DIR=${16}
unwarp_direction=${17}
ME=${18}
FDThres=${19}
FDTHRES=${20}
#NUMECHOS=${19}
rmfiles=${21:-''}

MIDVOL_UNWARP=${MIDVOL}_unwarp

# Use the true per-scan volume count from the data rather than the cfg NUMVOL.
# iProc's tasktype cfg carries ONE NUMVOL per task type, which is only valid
# when every run of a task has identical length (true for fixed-length rest
# acquisitions, false for variable-length task runs). A mismatched NUMVOL
# corrupts midvol selection (NUMVOL/2), the outlier percentage, the outlier
# matrix dimensions, and the motion regressors (p2a.sh tail -n NUMVOL). fslnvols
# is the authoritative count and makes every downstream use self-correcting.
# For genuinely fixed-length data this is a no-op (fslnvols == cfg NUMVOL).
NUMVOL=$(fslnvols ${MC_IN})

### ALL NEW UNTESTED BELOW #####
## only fd & then getting specific volume to be used and adding that to the filename rather than FINAL - so we can use that specific volume below

# Initial Selection of MidVol
#if [[ ! -e ${MC_IN%.nii.gz}_OrigMidVol.nii.gz ]]; then
fslroi ${MC_IN} ${MC_IN%.nii.gz}_OrigMidVol.nii.gz 'expr ${NUMVOL} / 2' 1  ## specific middle volume selected
echo $((${NUMVOL} / 2)) > ${MC_IN%.nii.gz}_OrigMidVol.txt
OrigMidVol=$((${NUMVOL} / 2))
#fi
# calculate FD outliers using the same FD threshold for REST and TASK
# now in the config file
#FDThres=0.4
#FDTHRES=0pt4
#if [[ ! -e ${MC_IN%.nii.gz}_FD_vals.txt ]]; then
fsl_motion_outliers -i ${MC_IN} -o ${MC_IN%.nii.gz}_FD${FDTHRES}_outlier_mat.txt -s ${MC_IN%.nii.gz}_FD_vals.txt -p ${MC_IN%.nii.gz}_FD.png --fd -v --thresh=${FDThres} > ${MC_IN%.nii.gz}_fsl_motion_outlier_FD${FDTHRES}_output.txt
#fi
grep 'Found spikes at ' ${MC_IN%.nii.gz}_fsl_motion_outlier_FD${FDTHRES}_output.txt > ${MC_IN%.nii.gz}_tmp1.txt

set +e
grep -Eo '[0-9]{1,4}' ${MC_IN%.nii.gz}_tmp1.txt > ${MC_IN%.nii.gz}_FD${FDTHRES}_outlier_num.txt
returncode=$?
set -e

if [ "${returncode}" -eq 0 ]; then
    echo "grep found spikes"
elif [ "${returncode}" -eq 1 ]; then
    echo "grep did not find any spikes"
else
    echo "grep errored with returncode ${returncode}"
    exit "${returncode}"
fi

#echo making list of outlier volumes
#grep -z '[0-9]{1,4}' ${MC_IN%.nii.gz}_tmp1.txt > ${MC_IN%.nii.gz}_FD${FDTHRES}_outlier_num.txt
#echo list compiled

if [[ ! -e ${MC_IN%.nii.gz}_FD${FDTHRES}_outlier_num.txt ]]; then
echo No Motion Spikes;
touch ${MC_IN%.nii.gz}_FD${FDTHRES}_outlier_num.txt
fi
OUTLIER_FILE="${MC_IN%.nii.gz}_FD${FDTHRES}_outlier_num.txt"
MIDVOL_NO="${OrigMidVol}"
num_outliers=$(cat ${OUTLIER_FILE} | wc -l)
pct=$(bc -l <<< ${num_outliers}/${NUMVOL})
status=$(echo "${pct} >= .2" | bc -l)
if [ "$status" == "1" ]; then
    echo "WARNING: number of outliers (${num_outliers}) is 20% or greater than the total number of volumes (${NUMVOL})"
fi
# search for midvol that is not an outlier
nits=5
found=false
echo "searching for a non-outlier midvol"
echo "starting with midvol number ${MIDVOL_NO}"
echo "stopping after ${nits} iterations"
for (( i = 1; i <= nits; i++ )); do
    set +e
    grep -q -w "${MIDVOL_NO}" "${OUTLIER_FILE}"
    returncode=$?
    set -e
    if [ ${returncode} -eq 0 ]; then
        echo "   ${i}. ${MIDVOL_NO} is an outlier"
    elif [ ${returncode} -eq 1 ]; then
        echo "   ${i}. ${MIDVOL_NO} is not an outlier (stop)"
        found=true
        break
    else
        exit ${returncode}
    fi
    MIDVOL_NO=$((${MIDVOL_NO} + 1))
done

if ! ${found}; then
    echo "unable to find a usable midvol"
    echo "exiting"
    exit 1
fi

echo "using ${MIDVOL_NO} as midvol"

# Create Final MidVol using updated MIDVOL or OrigMidVol
echo ${MIDVOL_NO} > ${MC_IN%.nii.gz}_FinalMidVol.txt


OUTLIERMATRIX="${MC_IN%.nii.gz}_FD${FDTHRES}_outlier_matrix.dat"
python ${CODEDIR}/runscript/create_motion_outlier_matrix.py $OUTLIER_FILE $NUMVOL $OUTLIERMATRIX



#rm ${MC_IN%.nii.gz}_tmp1.txt
#rm ${MC_IN%.nii.gz}_tmp2.txt

#### NOT Fully Tested! ^^ ########

# motion estimation and correction (within-run alignment)
mcflirt -in ${MC_IN} -out ${MC_OUT} -refvol ${MIDVOL_NO} -mats -plots -rmsrel -rmsabs -report  ## need this but after the specific middle volume has been selected & applying this to that.
fslroi ${MC_OUT} ${MIDVOL} ${MIDVOL_NO} 1 
# not going to pass on any warpfiles
${CODEDIR}/modwrap.sh 'module load fsl/4.0.3-ncf' 'module load fsl/5.0.4-ncf' ${CODEDIR}/runscript/fm_unw.sh ${FM_SESSID} ${FMdir} ${MIDVOL} ${MIDVOL_UNWARP} ${FM_BOLDNO} ${DEST_DIR} ${WARP_DIR} ${unwarp_direction} ${ME}

flirt -in ${MIDVOL_UNWARP} -ref ${TARGET} -out ${FLIRT_OUT} -omat ${FLIRT_MAT_OUT} -bins 256 -cost corratio -searchrx -180 180 -searchry -180 180 -searchrz -180 180 -dof 12 -interp trilinear 

#let "NUMMAT = $NUMVOL - 1"
#for THISVOL in $( seq 0 $NUMMAT ); do
#    #echo "THISVOL: " $THISVOL
#    if [ $THISVOL -lt 10 ]; then
#        convert_xfm -omat ${MC_OUT}.mat/CONCAT_000${THISVOL} -concat ${FLIRT_MAT_OUT} ${MC_OUT}.mat/MAT_000${THISVOL} 
#    elif [ $THISVOL -lt 100 ]; then
#        convert_xfm -omat ${MC_OUT}.mat/CONCAT_00${THISVOL} -concat ${FLIRT_MAT_OUT} ${MC_OUT}.mat/MAT_00${THISVOL} 
#    else
#        convert_xfm -omat ${MC_OUT}.mat/CONCAT_0${THISVOL} -concat ${FLIRT_MAT_OUT} ${MC_OUT}.mat/MAT_0${THISVOL} 
#    fi
#done
#echo "------- APPLYING COMBINED TRANSFORM FOR ECHO 1-------"
#applyxfm4D ${MC_IN} ${TARGET} ${FLIRT_OUT} ${MC_OUT}.mat -userprefix CONCAT_

#if [ "$ME" = "1" ]; then
#    for THISECHO in $( seq 2 $NUMECHOS ); do
#        echo " ----- APPLYING THE SAME TRANSFORM TO THE OTHER ECHO ${THISECHO} ----- "
#        THIS_MC_IN="${MC_IN/_e1/_e${THISECHO}}"
#        THIS_FLIRT_OUT="${FLIRT_OUT/midvoltarg_e1/midvoltarg_e${THISECHO}}"

#        echo $THIS_MC_IN
#        echo $THIS_FLIRT_OUT
#        applyxfm4D ${THIS_MC_IN} ${TARGET} ${THIS_FLIRT_OUT} ${MC_OUT}.mat -userprefix CONCAT_#

#    done
#fi


#EDITED to look for skip_mc_e1.par if ME is 1

${CODEDIR}/runscript/p2a.sh ${OUTDIR} ${SCAN_TYPE} ${NUMVOL} ${REGRESSORS_MC_DAT_OUT} ${ME}

if [ -n "$rmfiles" ]; then
    for f in $rmfiles;do
        rm -rf "$f"
    done
fi
