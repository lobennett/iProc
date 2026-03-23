#!/bin/bash
# build_sherlock.sh — Build iProc container on Stanford Sherlock
#
# Usage (on Sherlock):
#   cd $SCRATCH/iProc/container
#   sbatch build_sherlock.sh
#
# Or interactively on a dev node:
#   sdev -t 02:00:00 -m 32G
#   cd $SCRATCH/iProc/container
#   ./build_sherlock.sh
#
# Prerequisites:
#   - FreeSurfer license.txt in ./downloads/
#   - Internet access (login or dev nodes have this; compute nodes may not)

#SBATCH --job-name=iproc_build
#SBATCH --partition=normal
#SBATCH --time=02:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=4
#SBATCH --output=build_%j.log

set -euo pipefail

# When submitted via sbatch, SLURM copies the script to its spool directory.
# BASH_SOURCE would point there, not to the original location.
# Use SLURM_SUBMIT_DIR (where sbatch was invoked) if available.
if [[ -n "${SLURM_SUBMIT_DIR:-}" ]]; then
    SCRIPT_DIR="${SLURM_SUBMIT_DIR}"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
OUTPUT="${SCRIPT_DIR}/iproc.sif"

echo "============================================"
echo "  iProc Container Build (Sherlock)"
echo "  $(date)"
echo "============================================"

# Verify we're on a system with apptainer
if ! command -v apptainer &>/dev/null; then
    echo "ERROR: apptainer not found. Are you on Sherlock?"
    exit 1
fi

# Ensure downloads directory and license exist
mkdir -p "${SCRIPT_DIR}/downloads"
if [[ ! -f "${SCRIPT_DIR}/downloads/license.txt" ]]; then
    echo "ERROR: downloads/license.txt not found."
    echo "Copy your FreeSurfer license to: ${SCRIPT_DIR}/downloads/license.txt"
    exit 1
fi

echo "FreeSurfer license: OK"
echo "Apptainer version: $(apptainer --version)"
echo "Building: ${OUTPUT}"
echo ""

# Use SCRATCH for temp space (Apptainer needs lots of temp during build)
export APPTAINER_TMPDIR="${SCRATCH}/.apptainer_tmp"
mkdir -p "${APPTAINER_TMPDIR}"

cd "${SCRIPT_DIR}"
apptainer build --fakeroot --force "${OUTPUT}" iproc.def

# Clean up temp
rm -rf "${APPTAINER_TMPDIR}"

echo ""
echo "============================================"
echo "  Build complete: ${OUTPUT}"
echo "  Size: $(du -h "${OUTPUT}" | cut -f1)"
echo "  $(date)"
echo "============================================"
echo ""
echo "Test with:"
echo "  apptainer exec ${OUTPUT} bash -c 'source /opt/module_shim.sh; echo FSLDIR=\$FSLDIR; which bet2; which recon-all'"
