# BIDS-to-iProc Pipeline Guide

End-to-end workflow: from a BIDS dataset to fully preprocessed iProc outputs
on Stanford Sherlock HPC using the iProc Apptainer container.

## Prerequisites

- **Container built**: `iproc.sif` on Sherlock (see `container/README.md`)
- **uv available**: `module load uv` on Sherlock
- **BIDS dataset** on Oak storage

## Environment Setup

Set these once per shell session (or add to your `~/.bashrc`):

```bash
export BIDS_ROOT=/oak/stanford/groups/russpold/data/network_grant/discovery_BIDS_20250402
export IPROC_DIR=${BIDS_ROOT}/derivatives/iproc
export IPROC_CODE=$SCRATCH/iProc
export CONTAINER=$SCRATCH/iProc/container/iproc.sif
```

---

## Step 1: Discover

Scans the BIDS tree and produces an editable YAML manifest.

```bash
module load uv
cd $IPROC_CODE

# Single subject
uv run bids_setup/bids_discover.py $BIDS_ROOT \
    --output manifest.yaml \
    --skip 7 \
    --smoothing 0 \
    --resolution 111 \
    --echo-time-diff 0.002272 \
    --subjects s03

# All subjects
uv run bids_setup/bids_discover.py $BIDS_ROOT \
    --output manifest.yaml \
    --skip 7 \
    --smoothing 0 \
    --resolution 111 \
    --echo-time-diff 0.002272
```

| Flag | Default | Description |
|------|---------|-------------|
| `--skip` | 7 | Dummy volumes to discard from each functional run |
| `--smoothing` | 6.0 | FWHM smoothing kernel in mm (use 0 for surface analysis) |
| `--resolution` | 222 | Output template: 111=1mm, 222=2mm (use 111 for surface analysis) |
| `--echo-time-diff` | 0.002272 | Fieldmap echo time difference in seconds (2.272ms, GE CNI standard) |
| `--subjects` | all | Process only listed subjects (e.g. `--subjects s03 s10`) |

**Output:** `manifest.yaml` — review before proceeding.

### Review the manifest

```bash
cat manifest.yaml
```

Check:
- **t1_selection**: auto-picks the LATEST session with a T1w. Edit if needed.
- **midvol**: auto-picks first session, first BOLD, middle volume.
- **tasks**: verify TR, num_volumes, num_echos are correct.
- **Warnings**: sessions missing fieldmaps are flagged.

---

## Step 2: Generate iProc Configs

Reads the manifest and creates all configuration files. Also patches BIDS JSON
sidecars that are missing `SeriesNumber` or `EchoTimeDifference`.

```bash
uv run bids_setup/bids_generate.py manifest.yaml \
    --iproc-dir $IPROC_DIR \
    --codedir $IPROC_CODE
```

| Flag | Default | Description |
|------|---------|-------------|
| `--iproc-dir` | (required) | Output directory for iProc results (typically `derivatives/iproc`) |
| `--codedir` | same as iproc-dir | Path to iProc code repository (typically `$SCRATCH/iProc`) |
| `--fsldir` | `/opt/fsl-5.0.10` | FSLDIR inside the container |
| `--freesurfer-home` | `/opt/freesurfer-6.0.0` | FREESURFER_HOME inside the container |

**Creates:**
```
$IPROC_DIR/
  configs/tasktype_consolidated.csv
  mri_data/
    s03/subject_lists/
      scanlist_s03.csv
      s03.cfg
```

### Verify

```bash
head -20 $IPROC_DIR/mri_data/s03/subject_lists/s03.cfg
head -15 $IPROC_DIR/mri_data/s03/subject_lists/scanlist_s03.csv
cat $IPROC_DIR/configs/tasktype_consolidated.csv
grep ANAT $IPROC_DIR/mri_data/s03/subject_lists/scanlist_s03.csv
```

---

## Step 3: Prepare subjects.txt

Edit `bids_setup/subjects.txt` — one subject label per line:

```
s03
# s10   (commented out = skipped)
# s15
```

---

## Step 4: Run iProc Stages

Each stage is submitted as a SLURM job per subject. Wait for each stage to
complete before starting the next (check with `squeue -u $USER`).

### Stage 1: SETUP

Ingests BIDS data (fieldmaps, anatomicals, functionals) and runs FreeSurfer
`recon-all`.

```bash
cd $IPROC_CODE
./bids_setup/run_subjects.sh bids_setup/subjects.txt setup \
    --bids-root $BIDS_ROOT \
    --iproc-dir $IPROC_DIR \
    --container $CONTAINER \
    --time 24:00:00 --mem 32G
```

> `--bids-root` is required ONLY for the setup stage.

**Expected time:** 6-12 hours (dominated by `recon-all`). If you have
pre-computed FreeSurfer results, place them in `$IPROC_DIR/fs/{sub}/`
and iProc will skip `recon-all`.

**QC checkpoint before proceeding:**
- Check `fmap_qc` PDF for fieldmap quality
- Check `recon-all` surface registration (pial/WM boundaries on T1)
- Select the best T1 if multiple were collected -> update `T1_SESS` and
  `T1_SCAN_NO` in the `.cfg` file

### Stage 2: BET

Brain extraction on the MNI-warped T1.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt bet \
    --iproc-dir $IPROC_DIR --container $CONTAINER \
    --time 01:00:00 --mem 16G
```

**QC checkpoint:** Check brain extraction mask — too tight or too loose?

### Stage 3: UNWARP_MOTIONCORRECT_ALIGN

Motion correction, fieldmap unwarping, and alignment to midvol template.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt unwarp_motioncorrect_align \
    --iproc-dir $IPROC_DIR --container $CONTAINER \
    --time 08:00:00 --mem 32G
```

**QC checkpoint:** Check alignment of each run to the midvol and mean BOLD
templates. Review motion parameters (FD plots).

### Stage 4: T1_WARP_AND_MASK

Boundary-based registration, T1-to-MNI warp, and mask generation.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt T1_warp_and_mask \
    --iproc-dir $IPROC_DIR --container $CONTAINER \
    --time 04:00:00 --mem 32G
```

**QC checkpoint:** Check bbregister output (BOLD-to-T1 alignment) and brain
extraction of T1 in MNI space.

### Stage 5: COMBINE_AND_APPLY_WARP

Combines all transformation matrices and applies in a single interpolation
to native and MNI space.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt combine_and_apply_warp \
    --iproc-dir $IPROC_DIR --container $CONTAINER \
    --time 08:00:00 --mem 64G
```

> With 1mm resolution (111) and multi-echo data, this stage may need 64GB+.

**QC checkpoint:** Check single-interpolation QC PDFs. Verify fsaverage6
symlink exists in the subject's `recon_all` output.

### Stage 6 (Multi-echo): TEDANA

ICA-based denoising. Run between combine_and_apply_warp and filter_and_project.

```bash
apptainer exec --bind $OAK:/oak,$SCRATCH:/scratch $CONTAINER bash -c "
    source /opt/iproc-venv/bin/activate
    cd $IPROC_CODE && pip install -e . 2>/dev/null
    python tedana_loop.py
"
```

> Edit `tedana_loop.py` to set your subject ID, mri_data directory, and
> resolution before running.

### Stage 7: FILTER_AND_PROJECT

Nuisance regression, bandpass filtering, and surface projection to fsaverage6.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt filter_and_project \
    --iproc-dir $IPROC_DIR --container $CONTAINER \
    --time 08:00:00 --mem 32G
```

**Output per BOLD run:**
- `{BOLD}_anat.nii.gz` — native space volume
- `{BOLD}_mni.nii.gz` — MNI space volume
- `lh.{BOLD}_fsaverage6.nii.gz` — left hemisphere surface (unsmoothed)
- `rh.{BOLD}_fsaverage6.nii.gz` — right hemisphere surface (unsmoothed)
- `lh.{BOLD}_fsaverage6_sm{X}.nii.gz` — left hemisphere surface (smoothed)
- `rh.{BOLD}_fsaverage6_sm{X}.nii.gz` — right hemisphere surface (smoothed)

---

## run_subjects.sh Reference

```bash
./bids_setup/run_subjects.sh <subjects.txt> <stage> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--bids-root` | (none) | BIDS dataset root (required for setup stage only) |
| `--iproc-dir` | parent of this script | iProc output directory |
| `--container` | `$SCRATCH/containers/iproc.sif` | Path to container image |
| `--partition` | normal | SLURM partition |
| `--time` | 04:00:00 | Wall time |
| `--mem` | 32G | Memory |
| `--cpus` | 4 | CPUs per task |
| `--dry-run` | (flag) | Print sbatch commands without submitting |

**Valid stages:** `setup`, `bet`, `unwarp_motioncorrect_align`,
`T1_warp_and_mask`, `combine_and_apply_warp`, `filter_and_project`

---

## Monitoring and Troubleshooting

### Check running jobs
```bash
squeue -u $USER
```

### View job log
```bash
cat $IPROC_DIR/mri_data/s03/logs/slurm_setup_*.log
```

### Dry run (preview without submitting)
```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt setup \
    --bids-root $BIDS_ROOT --iproc-dir $IPROC_DIR --dry-run
```

### Cancel all iProc jobs
```bash
scancel -u $USER --name "iproc_*"
```

### Re-run a failed stage
Just re-submit. iProc skips already-completed steps by default. Use
`--overwrite` in the iProc command if you need to force re-processing.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| T1 selection | Latest session with T1w | Earlier T1s often re-collected due to low quality |
| MIDVOL target | First session, first BOLD, middle volume | Simple and deterministic |
| Skip volumes | 7 (flag: `--skip`) | Acquisition-specific dummy scans |
| Smoothing | 0mm for surface analysis (flag: `--smoothing`) | No volume-space smoothing when projecting to surface |
| Resolution | 111 = 1mm isotropic (flag: `--resolution`) | Upsampling from 2.8mm native improves surface projection quality |
| Echo time diff | 0.002272s (flag: `--echo-time-diff`) | GE CNI UHP spiral fieldmap standard (TE1=6.828ms, TE2=9.1ms) |
| Fieldmap type | `fsl_prepare_fieldmap` | Dual-echo gradient fieldmap (magnitude + phasediff) |
| SeriesNumbers | Synthetic when JSONs lack them | fmap_mag=2, fmap_phase=3, anat=50+run, bold=from JSON or sequential |
| CODEDIR vs BASEDIR | Separate paths | Code on $SCRATCH, outputs on $OAK |
