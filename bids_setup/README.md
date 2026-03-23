# BIDS-to-iProc Pipeline Guide

End-to-end workflow: from a BIDS dataset to fully preprocessed iProc outputs.

## Prerequisites

- **Container built**: `iproc.sif` on Sherlock (see `container/README.md`)
- **uv available**: `module load uv` on Sherlock
- **BIDS dataset** validated (consider running [BIDS Validator](https://bids-standard.github.io/bids-validator/) first)

## Quick Reference

```bash
# Full pipeline for a single subject (sub-s03):
uv run bids_setup/bids_discover.py /path/to/bids -o manifest.yaml --skip 7 --smoothing 0 --resolution 111 --subjects s03
uv run bids_setup/bids_generate.py manifest.yaml --iproc-dir /path/to/iProc
./bids_setup/run_subjects.sh bids_setup/subjects.txt setup   --bids-root /path/to/bids
./bids_setup/run_subjects.sh bids_setup/subjects.txt bet
./bids_setup/run_subjects.sh bids_setup/subjects.txt unwarp_motioncorrect_align
./bids_setup/run_subjects.sh bids_setup/subjects.txt T1_warp_and_mask
./bids_setup/run_subjects.sh bids_setup/subjects.txt combine_and_apply_warp
./bids_setup/run_subjects.sh bids_setup/subjects.txt filter_and_project
```

---

## Step 0: Prepare

### 0a. Edit subjects.txt

List subject labels (one per line, matching `sub-{label}` in BIDS):
```
s03
s10
s15
```

### 0b. Set variables (add to your shell or a wrapper script)

```bash
export BIDS_ROOT=/oak/stanford/groups/russpold/data/network_grant/discovery_BIDS_20250402
export IPROC_DIR=$OAK/path/to/iProc
export CONTAINER=$SCRATCH/containers/iproc.sif
```

---

## Step 1: Discover

Scans the BIDS tree and produces an editable YAML manifest.

```bash
uv run bids_setup/bids_discover.py $BIDS_ROOT \
    --output manifest.yaml \
    --skip 7 \
    --smoothing 0 \
    --resolution 111
```

**Flags:**
| Flag | Default | Description |
|------|---------|-------------|
| `--skip` | 7 | Dummy volumes to discard from each functional run |
| `--smoothing` | 6.0 | FWHM smoothing kernel in mm (use 0 for surface analysis) |
| `--resolution` | 222 | Output template: 111=1mm, 222=2mm (use 111 for surface analysis) |
| `--subjects` | all | Process only listed subjects (e.g. `--subjects s03 s10`) |

**Output:** `manifest.yaml`

### Review the manifest

Open `manifest.yaml` and check:
- **t1_selection**: auto-picks the LATEST session with a T1w. Change if needed.
- **midvol**: auto-picks first session, first BOLD, middle volume.
- **tasks**: verify TR, num_volumes, num_echos are correct.
- **Warnings**: any sessions missing fieldmaps will be flagged.

---

## Step 2: Generate iProc configs

Reads the manifest and creates all iProc configuration files.

```bash
uv run bids_setup/bids_generate.py manifest.yaml \
    --iproc-dir $IPROC_DIR
```

**Creates:**
```
iProc/
  configs/tasktype_consolidated.csv          # task parameters (one per study)
  mri_data/
    s03/subject_lists/
      scanlist_s03.csv                       # scan-to-fieldmap-to-anat mapping
      s03.cfg                                # subject config file
    s10/subject_lists/
      scanlist_s10.csv
      s10.cfg
    ...
```

### Verify generated files

Spot-check a few files:
```bash
cat configs/tasktype_consolidated.csv
cat mri_data/s03/subject_lists/scanlist_s03.csv
cat mri_data/s03/subject_lists/s03.cfg
```

---

## Step 3: SETUP

Ingests BIDS data (fieldmaps, anatomicals, functionals) and runs FreeSurfer `recon-all`.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt setup \
    --bids-root $BIDS_ROOT \
    --time 24:00:00 \
    --mem 32G
```

> **Note:** `--bids-root` is required ONLY for the setup stage. All other
> stages read from iProc's internal data structure.

**Expected time:** 6-12 hours (dominated by `recon-all`).
If you have pre-computed FreeSurfer results, place them in `fs/{sub}/` and
iProc will skip `recon-all`.

### QC checkpoint before proceeding:
- Check `fmap_qc` PDF for fieldmap quality
- Check `recon-all` surface registration (pial/WM boundaries on T1)
- Select the best T1 if multiple were collected → update `T1_SESS` and
  `T1_SCAN_NO` in the `.cfg` file

---

## Step 4: BET

Brain extraction on the MNI-warped T1.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt bet \
    --time 01:00:00 \
    --mem 16G
```

### QC checkpoint:
- Check brain extraction — is the mask too tight or too loose?
- If needed, re-run BET with adjusted parameters (see iProc tutorial §7.3)

---

## Step 5: UNWARP_MOTIONCORRECT_ALIGN

Motion correction, fieldmap unwarping, and alignment to midvol template.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt unwarp_motioncorrect_align \
    --time 08:00:00 \
    --mem 32G
```

### QC checkpoint:
- Check alignment of each run to the midvol and mean BOLD templates
- Review motion parameters (FD plots)

---

## Step 6: T1_WARP_AND_MASK

Boundary-based registration, T1→MNI warp computation, and mask generation.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt T1_warp_and_mask \
    --time 04:00:00 \
    --mem 32G
```

### QC checkpoint:
- Check boundary-based registration (BOLD→T1 alignment)
- Check brain extraction of T1 in MNI space

---

## Step 7: COMBINE_AND_APPLY_WARP

Combines all transformation matrices and applies them in a single interpolation
to both native (anatomical) and MNI space.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt combine_and_apply_warp \
    --time 08:00:00 \
    --mem 64G
```

> **Memory note:** With 1mm resolution (111) and multi-echo data, this stage
> may need 64GB+ RAM. If jobs fail with OOM, increase `--mem`.

### QC checkpoint:
- Check single-interpolation QC PDFs
- Verify fsaverage6 symlink exists in the subject's `recon_all` output

---

## Step 8: TEDANA (Multi-echo only)

ICA-based denoising for multi-echo data. Run between combine_and_apply_warp
and filter_and_project.

```bash
# TEDANA is run per-subject via the tedana_loop.py script
apptainer exec --bind $OAK:/oak,$SCRATCH:/scratch $CONTAINER bash -c "
    source /opt/iproc-venv/bin/activate
    cd $IPROC_DIR
    python tedana_loop.py
"
```

> Edit `tedana_loop.py` to set your subject ID, mri_data directory, and
> resolution before running.

---

## Step 9: FILTER_AND_PROJECT

Nuisance regression, bandpass filtering, and surface projection to fsaverage6.

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt filter_and_project \
    --time 08:00:00 \
    --mem 32G
```

### QC checkpoint:
- Check output data exists in both native and MNI space
- Verify surface-projected data (`.mgz` files)

---

## Monitoring Jobs

```bash
# Check running jobs
squeue -u $USER

# Check a specific job's log
cat mri_data/s03/logs/slurm_setup_*.log

# Cancel all iProc jobs
scancel -u $USER --name "iproc_*"
```

## Dry Run

Preview sbatch commands without submitting:

```bash
./bids_setup/run_subjects.sh bids_setup/subjects.txt setup \
    --bids-root $BIDS_ROOT --dry-run
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| T1 selection | Latest session with T1w | Earlier T1s often re-collected due to low quality |
| MIDVOL target | First session, first BOLD, middle volume | Simple and deterministic |
| Skip volumes | 7 (flag: `--skip`) | Acquisition-specific dummy scans |
| Smoothing | 0mm for surface analysis (flag: `--smoothing`) | No volume-space smoothing when projecting to surface |
| Resolution | 111 = 1mm isotropic (flag: `--resolution`) | Upsampling from 2.8mm native improves surface projection quality |
| Fieldmap type | `fsl_prepare_fieldmap` | Dual-echo gradient fieldmap (magnitude + phasediff) |
