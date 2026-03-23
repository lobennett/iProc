# iProc Container Build Guide

Apptainer (Singularity) container for the iProc v2.6 preprocessing pipeline,
designed for Stanford Sherlock HPC.

## What's Inside

| Software | Version | Purpose |
|----------|---------|---------|
| FSL | 4.1.9 / 5.0.8 / 6.0.7 | Core neuroimaging (multi-version, runtime-switched) |
| FreeSurfer | 6.0.0 | Surface reconstruction (`recon-all`) |
| AFNI | 16.3.13 | Regression (`3dTproject`) |
| ANTs | 2.4.4 | Advanced normalization |
| Python | 3.11 | iProc runtime + tedana |
| GNU Parallel | 20180522 | Task parallelization |
| dcm2niix | 1.0.20230411 | DICOM-to-NIfTI conversion |
| ImageMagick | system | QC image generation |
| Connectome Workbench | 1.3.2 | Surface data tools |
| MRIcroGL | 2019.09.04 | Visualization |
| tedana | latest | Multi-echo ICA denoising |

**MATLAB is NOT required** — fully replaced by Python in the iProc codebase.

## FSL Version Mapping

iProc switches between FSL 4.0.3, 5.0.4, 5.0.10, and 6.0.1 at runtime.
FSL no longer distributes those exact versions as binaries. The container
installs the closest available and maps them via symlinks + module shim:

| iProc requests | Container installs | Source |
|---|---|---|
| 4.0.3 | 4.1.9 | fsl.fmrib.ox.ac.uk/fsldownloads/oldversions/ |
| 5.0.4, 5.0.10 | 5.0.8 | fsl.fmrib.ox.ac.uk/fsldownloads/oldversions/ |
| 6.0.1 | 6.0.7+ | fslinstaller.py (conda) |

**To use the exact validated versions**, copy them from Sherlock (see below).

## Build (Quick Start)

The only file you need to provide is the FreeSurfer license. Everything
else downloads automatically during the build.

```bash
cd iProc/container

# FreeSurfer license (already in place if you followed setup)
ls downloads/license.txt   # should exist

# Build (~30-60 min, needs ~25 GB disk, internet access)
./build.sh
```

## (Optional) Use Exact FSL Versions from Sherlock

If you want bit-identical reproduction of iProc's validated pipeline, copy
the exact FSL installations from Sherlock before building:

```bash
# SSH into Sherlock
ssh ${USER}@login.sherlock.stanford.edu

# For each FSL version, find and tar the installation:
module load system
module load fsl/4.0.3    # or however Sherlock names it
tar czf fsl-4.0.3.tar.gz -C $(dirname $FSLDIR) $(basename $FSLDIR)

module swap fsl/4.0.3 fsl/5.0.4
tar czf fsl-5.0.4.tar.gz -C $(dirname $FSLDIR) $(basename $FSLDIR)

module swap fsl/5.0.4 fsl/5.0.10
tar czf fsl-5.0.10.tar.gz -C $(dirname $FSLDIR) $(basename $FSLDIR)

# Copy back to your Mac
exit
scp ${USER}@login.sherlock.stanford.edu:fsl-*.tar.gz container/downloads/
```

Then uncomment the corresponding `%files` lines in `iproc.def` and rebuild.

## Transfer to Sherlock

```bash
scp iproc.sif ${USER}@login.sherlock.stanford.edu:$SCRATCH/containers/
```

## Running on Sherlock

### Interactive test
```bash
apptainer shell --bind $SCRATCH:/scratch,$OAK:/oak \
    $SCRATCH/containers/iproc.sif
```

Inside the container:
```bash
source /opt/iproc-venv/bin/activate
cd /path/to/iProc
pip install -e .      # first time only
iProc.py --help
```

### SLURM batch job
```bash
#!/bin/bash
#SBATCH --job-name=iproc_setup
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4

CONTAINER=$SCRATCH/containers/iproc.sif
IPROC_DIR=$OAK/path/to/iProc
CONFIG=$OAK/path/to/mri_data/SUB/subject_lists/SUB.cfg
BIDS=$OAK/path/to/bids/sub-SUB

apptainer exec \
    --bind $SCRATCH:/scratch,$OAK:/oak \
    $CONTAINER \
    bash -c "
        source /opt/iproc-venv/bin/activate
        cd ${IPROC_DIR}
        pip install -e . 2>/dev/null
        python iProc.py -c ${CONFIG} -s setup --bids ${BIDS} --executor local
    "
```

### All stages in sequence
```bash
for stage in setup bet unwarp_motioncorrect_align T1_warp_and_mask \
             combine_and_apply_warp filter_and_project; do
    apptainer exec --bind $SCRATCH:/scratch,$OAK:/oak \
        $CONTAINER bash -c "
            source /opt/iproc-venv/bin/activate
            cd ${IPROC_DIR}
            python iProc.py -c ${CONFIG} -s ${stage} --bids ${BIDS} --executor local
        "
done
```

## How the Module Shim Works

The `module_shim.sh` defines a bash `module()` function that intercepts
`module load fsl/X.Y.Z-ncf` calls and swaps `FSLDIR` + `PATH` to point
at the correct `/opt/fsl-{version}` installation. No iProc source code
changes are needed.

The shim is loaded via:
- `BASH_ENV=/opt/module_shim.sh` for non-interactive shells (Python subprocess)
- `/etc/profile.d/module_shim.sh` for login shells
- `/bin/sh -> bash` so Python's `shell=True` uses bash

## Troubleshooting

### "module: command not found"
```bash
apptainer exec iproc.sif bash -c 'type module'
# Should output: module is a function
```

### FSL version not switching
```bash
apptainer exec iproc.sif bash -c '
    source /opt/module_shim.sh
    echo "Default: $FSLDIR"
    module load fsl/4.0.3-ncf
    echo "After 4.0.3: $FSLDIR"
    module load fsl/6.0.1-ncf
    echo "After 6.0.1: $FSLDIR"
'
```

### Old FSL binaries fail with glibc errors
If FSL 4.1.9 binaries crash on Ubuntu 22.04, change the base image in
`iproc.def` line 2 to `rockylinux:8` and swap `apt-get` for `dnf`.

### FreeSurfer license errors
The license is baked into the image. You can also override at runtime:
```bash
apptainer exec --bind /path/to/license.txt:/opt/freesurfer-6.0.0/license.txt ...
```
