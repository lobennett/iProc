# Sherlock + BIDS Tooling Audit

**Date:** 2026-05-17
**Branch under review:** container-and-bids-tooling
**Upstream baseline:** upstream/main @ 1816333c904c6cb94d9bd972a24b8ddf3d04572b

## Divergence

- Commits ahead of upstream: 22 (pre-audit-commit count; after this audit doc commit lands becomes 23)
- Commits behind upstream: 12
- Decision: defer

Rationale: The 12 upstream commits split into two clusters: (1) docs/tutorial/quickstart PDFs and mkdocs reorganization (c98f040, 50c3985) and (2) a "minor_fix" PR series (9db2154, cf67ebe, 8809fb9, 7cd5bf4, 0a72331, de2282d, 3847bea, 2c929d5) plus multi-echo fixes (6838adf, 1816333). The minor_fix cluster touches `runscript/anat_from_bids.py`, `runscript/func_from_bids.py`, `runscript/fmap_from_bids_topup.sh`, `runscript/fmap_topup_prep.sh`, `runscript/calculate_nuisance_params.sh`, `runscript/fs6_project_to_surf.sh`, `modwrap.sh`, `modules_rocky8.sh`, `iProc_p4_sbatch_combined_ME.py`, `tedana-requirements.txt`, `iproc/steps.py`, and `pyproject.toml`. Of these, `iproc/steps.py` overlaps with WIP commits on this branch. Upstream also touched `runscript/anat_from_bids.py` — the exact stage where sub-s03 stalled — with a "Fix possible wrong working dir" patch. The overlap on `iproc/steps.py` means a blind merge carries conflict risk. However, since we are switching from sub-s03 to sub-s10 as the test subject and have not yet begun Phase 2 coding, the risk of deferral (leaving branch diverged) is low right now. Recommended action: cherry-pick `9db2154` (anat_from_bids.py working-dir fix) as a standalone step at the start of Phase 2, and schedule a full rebase onto upstream/main before any PR back upstream. Do not merge wholesale now.

## What's on container-and-bids-tooling (one line per commit)

### container

- `50c9e6b` feat: add Apptainer container and BIDS-to-iProc config generation tooling — initial commit adding container/ dir (iproc.def, build.sh, build_sherlock.sh, validate.sh, module_shim.sh) and bids_setup/ tooling
- `37047b7` fix: use SLURM_SUBMIT_DIR for build script path resolution — container/build_sherlock.sh SLURM path fix
- `880a03c` fix: install gpg before adding deadsnakes PPA — container/iproc.def apt ordering fix
- `8c93117` fix: default env vars in validate.sh for standalone execution — container/validate.sh env-var guard
- `8d7b640` fix: FSL 5.0.8 download, AFNI binary dist, numpy pinning, GNU Parallel — container/iproc.def multi-fix (FSL, AFNI, numpy==1.25.2, parallel)
- `bf4a828` fix: add --force to apptainer build to overwrite existing .sif — container/build_sherlock.sh idempotency
- `4224381` fix: constrain numpy==1.25.2 during tedana dep install — container/iproc.def numpy pin tightened
- `6ac62dd` fix: use bash for %post section (Apptainer defaults to /bin/sh) — container/iproc.def shell fix

### bids-adapter

- `b4445cd` feat: handle missing JSON sidecars — synthetic SeriesNumbers + JSON patching — iproc/bids/__init__.py + bids_setup/ sidecar repair
- `12cffb0` fix: use FMAP_AP/FMAP_PA column names to match iProc's CSV schema — bids_setup/bids_generate.py column names
- `fb04ae6` fix: copy cluster_requests.csv from code repo to output configs dir — bids_setup/bids_generate.py config copy
- `b459345` fix: skip anat JSON check for sessions without anat scans — bids_setup/bids_discover.py guard clause

### sherlock-fix

- `224a6db` fix: bind /oak:/oak (not $OAK:/oak), cd to codedir not output dir — bids_setup/run_subjects.sh bind path + cwd fix
- `c4b9fc3` fix: capture stderr in separate .err log, echo iProc command before running — bids_setup/run_subjects.sh logging
- `6b04dc7` fix: fmap_from_bids.py — read scanner/delta_te from JSON, remove module load — runscript/fmap_from_bids.py JSON read + module fix
- `f786f1c` fix: wrap BIDS fieldmap filenames in list before cmd.extend() — runscript/fmap_from_bids.py type fix
- `6c2573c` fix: remove iproc.commons dependency from fmap_from_bids.py — runscript/fmap_from_bids.py import cleanup
- `3bc9094` debug: add logging to fmap JSON sidecar lookup — runscript/fmap_from_bids.py debug logging
- `d1bcf28` fix: save fmapp input paths before merge() pops from list — runscript/fmap_from_bids.py list-pop bug
- `59e4d7c` fix: handle GE fieldmaps directly — fsl_prepare_fieldmap only supports SIEMENS/VARIAN — runscript/fmap_from_bids.py GE scanner branch

### docs

- `03e63e1` docs: add full pipeline guide for BIDS-to-iProc workflow — docs/ pipeline guide
- `951d155` docs: update pipeline README with complete Sherlock workflow — docs/ README update

## What's untested

Subjects attempted: s03 only. Stalled at `anat_from_bids.py` (stage 0 — wrong working directory). The pipeline has never produced an end-to-end subject. Switching to sub-s10 from `/scratch/users/logben/discovery_bids` for Phase 2 onward.

Note: upstream commit `9db2154` ("Fix possible wrong working dir", touching `runscript/anat_from_bids.py`) may directly fix the stage-0 stall. Cherry-pick recommended as Phase 2 first step before any Sherlock-specific fixes.

## Container verification

iproc.sif present at /scratch/users/logben/iProc/container/iproc.sif: Y

Last built: 2026-03-25 16:25:19 PDT (mtime)

Contains nibabel/scipy/matplotlib (Phase 5 needs these)? Verified via:

```
apptainer exec container/iproc.sif python -c "import nibabel, scipy, matplotlib, numpy; print('all imports ok')"
```

Result: **all imports ok**

All Phase 5 Python dependencies (nibabel, scipy, matplotlib, numpy) are present in the existing container. No container rebuild required as a Phase 5 prerequisite.
