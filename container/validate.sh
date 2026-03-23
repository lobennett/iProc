#!/bin/bash
# validate.sh — Verify all iProc dependencies are functional inside the container
#
# Usage:
#   apptainer exec iproc.sif bash validate.sh
#   OR
#   apptainer shell iproc.sif
#   $ bash validate.sh
set -u

PASS=0
FAIL=0
WARN=0

pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  [WARN] $1"; WARN=$((WARN + 1)); }

check_cmd() {
    local cmd="$1"
    local label="${2:-$cmd}"
    if command -v "$cmd" &>/dev/null; then
        pass "$label: $(command -v $cmd)"
    else
        fail "$label: not found on PATH"
    fi
}

check_version() {
    local cmd="$1"
    local expected="$2"
    local actual
    actual=$($cmd 2>&1 | head -5) || true
    if [[ -n "$actual" ]]; then
        pass "$cmd version info available"
    else
        warn "$cmd produced no version output"
    fi
}

echo "============================================"
echo "  iProc Container Validation"
echo "  $(date)"
echo "============================================"
echo ""

# ------------------------------------------------------------------
echo "--- 1. Module Shim ---"
# ------------------------------------------------------------------
source /opt/module_shim.sh 2>/dev/null
if type module &>/dev/null; then
    pass "module function available"
else
    fail "module function not defined"
fi

# Test FSL switching
original_fsldir="$FSLDIR"
module load fsl/4.0.3-ncf
if [[ "$FSLDIR" == *"4.0.3"* ]] || [[ "$FSLDIR" == *"4.1.9"* ]]; then
    pass "module load fsl/4.0.3-ncf -> FSLDIR=$FSLDIR"
else
    fail "module load fsl/4.0.3-ncf -> FSLDIR=$FSLDIR (expected 4.0.3 or 4.1.9)"
fi

module load fsl/5.0.4-ncf
if [[ "$FSLDIR" == *"5.0"* ]]; then
    pass "module load fsl/5.0.4-ncf -> FSLDIR=$FSLDIR"
else
    fail "module load fsl/5.0.4-ncf -> FSLDIR=$FSLDIR"
fi

module load fsl/5.0.10-centos7_x64-ncf
if [[ "$FSLDIR" == *"5.0"* ]]; then
    pass "module load fsl/5.0.10-* -> FSLDIR=$FSLDIR"
else
    fail "module load fsl/5.0.10-* -> FSLDIR=$FSLDIR"
fi

module load fsl/6.0.1-ncf
if [[ "$FSLDIR" == *"6.0"* ]]; then
    pass "module load fsl/6.0.1-ncf -> FSLDIR=$FSLDIR"
else
    fail "module load fsl/6.0.1-ncf -> FSLDIR=$FSLDIR"
fi

# Restore default
export FSLDIR="$original_fsldir"
export PATH="${FSLDIR}/bin:$(echo $PATH | tr ':' '\n' | grep -v '/opt/fsl-.*/bin' | tr '\n' ':')"

echo ""

# ------------------------------------------------------------------
echo "--- 2. FSL Commands (version-specific) ---"
# ------------------------------------------------------------------

# Test FSL 4.0.3/4.1.9 commands (bet2, fugue, sigloss)
module load fsl/4.0.3-ncf
check_cmd bet2 "bet2 (FSL 4.0.3 slot)"
check_cmd fugue "fugue (FSL 4.0.3 slot)"
check_cmd sigloss "sigloss (FSL 4.0.3 slot)"
check_cmd fslmaths "fslmaths (FSL 4.0.3 slot)"

# Test FSL 5.0.4 commands (fsl_prepare_fieldmap)
module load fsl/5.0.4-ncf
check_cmd fsl_prepare_fieldmap "fsl_prepare_fieldmap (FSL 5.0.4 slot)"

# Test FSL default (5.0.10) commands
module load fsl/5.0.10-centos7_x64-ncf
for cmd in fslmerge fslroi fslmaths fslreorient2std flirt fnirt mcflirt \
           applywarp convertwarp invwarp convert_xfm fslmeants fslstats \
           fslhd fslswapdim fsl_motion_outliers; do
    check_cmd "$cmd" "$cmd (FSL 5.0.10 slot)"
done

# Test FSL 6.0.1 commands (topup)
module load fsl/6.0.1-ncf
check_cmd topup "topup (FSL 6.0.1 slot)"
check_cmd applytopup "applytopup (FSL 6.0.1 slot)"

echo ""

# ------------------------------------------------------------------
echo "--- 3. FSL Functional Tests ---"
# ------------------------------------------------------------------

# Quick test: can fslhd actually run on a real file?
module load fsl/5.0.10-centos7_x64-ncf
MNI="${FSLDIR}/data/standard/MNI152_T1_2mm.nii.gz"
if [[ -f "$MNI" ]]; then
    dims=$(fslhd "$MNI" 2>/dev/null | grep -E "^dim[1-3]" | head -3)
    if [[ -n "$dims" ]]; then
        pass "fslhd reads MNI152 template: $(echo $dims | tr '\n' ' ')"
    else
        fail "fslhd could not read MNI152 template"
    fi

    # Test fslinfo (volume count)
    nvols=$(fslnvols "$MNI" 2>/dev/null || echo "N/A")
    if [[ "$nvols" != "N/A" ]]; then
        pass "fslnvols works: MNI152 has $nvols volume(s)"
    else
        warn "fslnvols not available (not critical)"
    fi
else
    warn "MNI152 template not found at $MNI — skipping functional FSL tests"
fi

# Test that Python subprocess can use module shim (the critical path)
result=$(python3 -c "
import subprocess
r = subprocess.run('source /opt/module_shim.sh && module load fsl/4.0.3-ncf && which bet2',
                   shell=True, capture_output=True, text=True)
print(r.stdout.strip())
" 2>/dev/null)
if [[ -n "$result" ]] && [[ "$result" == *"bet2"* ]]; then
    pass "Python subprocess + module shim works: $result"
else
    fail "Python subprocess + module shim failed (output: '$result')"
fi

echo ""

# ------------------------------------------------------------------
echo "--- 4. FreeSurfer ---"
# ------------------------------------------------------------------
check_cmd recon-all "recon-all"
check_cmd mri_convert "mri_convert"
check_cmd mri_vol2surf "mri_vol2surf"
check_cmd mri_surf2surf "mri_surf2surf"
check_cmd bbregister "bbregister"

if [[ -f "$FS_LICENSE" ]]; then
    pass "FreeSurfer license exists at $FS_LICENSE"
else
    fail "FreeSurfer license missing at $FS_LICENSE"
fi

if [[ -d "${FREESURFER_HOME}/subjects/fsaverage6" ]]; then
    pass "fsaverage6 atlas present"
else
    warn "fsaverage6 atlas not found (needed for surface projection)"
fi

echo ""

# ------------------------------------------------------------------
echo "--- 5. AFNI ---"
# ------------------------------------------------------------------
check_cmd 3dTproject "3dTproject"
check_cmd 3dAFNItoNIFTI "3dAFNItoNIFTI"

echo ""

# ------------------------------------------------------------------
echo "--- 6. Other Tools ---"
# ------------------------------------------------------------------
check_cmd parallel "GNU Parallel"
check_cmd dcm2niix "dcm2niix"
check_cmd convert "ImageMagick convert"
check_cmd antsRegistration "ANTs antsRegistration"
check_cmd wb_command "Connectome Workbench wb_command"

echo ""

# ------------------------------------------------------------------
echo "--- 7. Python Environment ---"
# ------------------------------------------------------------------
source /opt/iproc-venv/bin/activate 2>/dev/null

python_ok=true
for pkg in nibabel texttable paramiko numpy scipy matplotlib yaml configparser; do
    if python3 -c "import $pkg" 2>/dev/null; then
        pass "Python: import $pkg"
    else
        fail "Python: import $pkg failed"
        python_ok=false
    fi
done

# tedana
if python3 -c "import tedana" 2>/dev/null; then
    pass "Python: import tedana"
else
    fail "Python: import tedana failed"
fi

# Check numpy version specifically (iProc needs 1.25.2)
np_ver=$(python3 -c "import numpy; print(numpy.__version__)" 2>/dev/null)
if [[ "$np_ver" == "1.25.2" ]]; then
    pass "numpy version: $np_ver (exact match)"
else
    warn "numpy version: $np_ver (expected 1.25.2)"
fi

echo ""

# ------------------------------------------------------------------
echo "--- 8. BASH_ENV (Critical for iProc) ---"
# ------------------------------------------------------------------
if [[ "$BASH_ENV" == "/opt/module_shim.sh" ]]; then
    pass "BASH_ENV=$BASH_ENV"
else
    fail "BASH_ENV='$BASH_ENV' (expected /opt/module_shim.sh)"
fi

# Verify /bin/sh is bash
sh_target=$(readlink -f /bin/sh)
if [[ "$sh_target" == *"bash"* ]]; then
    pass "/bin/sh -> $sh_target (bash)"
else
    fail "/bin/sh -> $sh_target (expected bash)"
fi

echo ""

# ------------------------------------------------------------------
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed, $WARN warnings"
echo "============================================"

if [[ $FAIL -gt 0 ]]; then
    echo "  Some checks FAILED. Review output above."
    exit 1
else
    echo "  Container is ready for iProc."
    exit 0
fi
