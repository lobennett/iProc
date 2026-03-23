#!/bin/bash
# build.sh — Build the iProc Apptainer container image
#
# Usage:
#   cd iProc/container
#   ./build.sh [output_name]
#
# Prerequisites:
#   1. Apptainer (or Singularity >= 3.0) installed
#   2. FreeSurfer license.txt in ./downloads/
#   3. (Optional) Exact FSL versions from Sherlock in ./downloads/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${1:-iproc.sif}"

echo "============================================"
echo "  iProc Container Build"
echo "============================================"

# Ensure downloads directory exists
mkdir -p "${SCRIPT_DIR}/downloads"

# Check for FreeSurfer license (the only hard requirement)
if [[ ! -f "${SCRIPT_DIR}/downloads/license.txt" ]]; then
    echo "ERROR: downloads/license.txt not found."
    echo ""
    echo "You need a FreeSurfer license file. Get one free at:"
    echo "  https://surfer.nmr.mgh.harvard.edu/registration.html"
    echo ""
    echo "Then copy it to: ${SCRIPT_DIR}/downloads/license.txt"
    exit 1
fi

echo "FreeSurfer license found."
echo ""

# Check for optional Sherlock FSL tarballs
sherlock_count=0
for ver in 4.0.3 5.0.4 5.0.10; do
    if [[ -f "${SCRIPT_DIR}/downloads/fsl-${ver}.tar.gz" ]]; then
        echo "Found exact FSL ${ver} from Sherlock"
        sherlock_count=$((sherlock_count + 1))
    fi
done

if [[ $sherlock_count -eq 0 ]]; then
    echo "No Sherlock FSL tarballs found — will use closest public versions:"
    echo "  4.0.3 → 4.1.9, 5.0.4/5.0.10 → 5.0.8, 6.0.1 → 6.0.7"
    echo ""
    echo "To use exact versions, copy them from Sherlock first:"
    echo "  # On Sherlock:"
    echo "  module load fsl/4.0.3"
    echo '  tar czf fsl-4.0.3.tar.gz -C $(dirname $FSLDIR) $(basename $FSLDIR)'
    echo "  # ... repeat for 5.0.4 and 5.0.10"
    echo "  # Then scp to ./downloads/"
fi
echo ""

echo "Building container (this will take 30-60 minutes)..."
echo ""

cd "${SCRIPT_DIR}"
apptainer build "${OUTPUT}" iproc.def

echo ""
echo "============================================"
echo "  Build complete: ${OUTPUT}"
echo "  Size: $(du -h "${OUTPUT}" | cut -f1)"
echo "============================================"
echo ""
echo "Transfer to Sherlock:"
echo "  scp ${OUTPUT} \${USER}@login.sherlock.stanford.edu:\$SCRATCH/containers/"
