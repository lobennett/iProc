#!/bin/sh
set -xeou pipefail
# iProc_p5a.sh
# R. Braga 2018

RESID_IN=$1
CSF_TS=$2
CSF_MASK=$3
WM_TS=$4
WM_MASK=$5
WB_TS=$6
WB_MASK=$7
PHYS_TS=$8
MC_TS=$9
NUIS_TS=${10}
SCANG=${11}
NUIS_OUT=${12}
OUTDIR=${13}
MCOUT_TS=${14}
NUIS_OUT_NOCENSOR=${15}
CODE_DIR=${16}

tmpdir=$(mktemp --directory --tmpdir=${OUTDIR})

if command -v parallel &>/dev/null; then
    parallel -j 3 --tmpdir=${tmpdir} <<EOF
fslmeants -i ${RESID_IN} -o ${CSF_TS} -m ${CSF_MASK}
fslmeants -i ${RESID_IN} -o ${WM_TS} -m ${WM_MASK}
fslmeants -i ${RESID_IN} -o ${WB_TS} -m ${WB_MASK}
EOF
else
    fslmeants -i ${RESID_IN} -o ${CSF_TS} -m ${CSF_MASK}
    fslmeants -i ${RESID_IN} -o ${WM_TS} -m ${WM_MASK}
    fslmeants -i ${RESID_IN} -o ${WB_TS} -m ${WB_MASK}
fi
# note: this WB_TS is identical in all respects to the one produced
#by runscript/remove_WB_only.sh
printf "%0.3f\n" `cat ${WB_TS}` > ${WB_TS}
printf "%0.3f\n" `cat ${CSF_TS}` > ${CSF_TS}
printf "%0.3f\n" `cat ${WM_TS}` > ${WM_TS}

paste -d ' ' ${CSF_TS} ${WM_TS} ${WB_TS} | awk '$1!~/#/{printf("%10.3f%10.3f%10.3f\n", $1, $2, $3)}' > ${PHYS_TS}

paste -d ' ' ${MC_TS} ${PHYS_TS} | tr -s " " > ${NUIS_TS}

#TODO: different matlab version?
# this prevents the matlab program from failing silently on character-limit of 63, as it had before.
pushd $tmpdir

# Prepare regressor matrix in matlab
# detrend and normalized, calculate temporal derivatives (18P) and the quadratric term (36P)
# Updates to original command to convert to 36P matrix
# Satterthwaite et al., 2013, Neuroimage

# Original:
#matlab -nojvm -nodesktop -nosplash -r "try e=0; format long g; nuis_ts=load('${NUIS_TS}'); xx=diff(zscore(detrend(nuis_ts))); x=zscore(detrend(nuis_ts)); xx=[zeros(size(xx(1,1:end)));xx]; xxx=[x xx]; dlmwrite('${tmpdir}/nuis_out.dat',xxx,'delimiter', ' ', 'precision',10); catch e=1; end; exit(e)"

# Updated:
#matlab -nojvm -nodesktop -nosplash -r "try e=0; format long g; nuis_ts=load('${NUIS_TS}'); nuis_norm=zscore(detrend(nuis_ts)); nuis_deriv1=diff(nuis_norm); nuis_deriv1=[zeros(size(nuis_deriv1(1,1:end)));nuis_deriv1]; nuis_18P=[nuis_norm nuis_deriv1]; nuis_quad=nuis_18P .^2; FULLNUISDF=[nuis_norm nuis_deriv1 nuis_quad]; dlmwrite('${tmpdir}/nuis_out.dat', FULLNUISDF,'delimiter', ' ', 'precision',10); catch e=1; end; exit(e)"

#without MATLAB
echo ${CODE_DIR}
python ${CODE_DIR}/runscript/calculate_nuisance_params.py ${NUIS_TS} ${tmpdir}


rsync -av $tmpdir/nuis_out.dat "${NUIS_OUT_NOCENSOR}"
rm -rf ${tmpdir}
#we used to remove timeseries data, but from now on we'll keep it
# add the motion outliers  to NUIS_OUT
paste -d ' ' ${NUIS_OUT_NOCENSOR} ${MCOUT_TS} | tr -s " " > ${NUIS_OUT}
