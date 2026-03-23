# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pyyaml>=5.0",
# ]
# ///
"""
bids_generate.py — Generate iProc configuration files from a BIDS manifest.

Usage:
    uv run bids_generate.py manifest.yaml --iproc-dir /path/to/iProc

Reads the manifest produced by bids_discover.py and generates:
  1. configs/tasktype_consolidated.csv
  2. mri_data/{sub}/subject_lists/scanlist_{sub}.csv  (per subject)
  3. mri_data/{sub}/subject_lists/{sub}.cfg            (per subject)

The manifest should be reviewed/edited before running this script.
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import sys
from pathlib import Path
from typing import Any

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sanitization (match iProc's BIDS session ID logic)
# ---------------------------------------------------------------------------

def sanitize(s: str) -> str:
    """Remove non-alphanumeric chars for iProc session IDs."""
    return re.sub(r"[^a-zA-Z0-9]", "", str(s))


# ---------------------------------------------------------------------------
# Generate tasktype_consolidated.csv
# ---------------------------------------------------------------------------

def generate_tasktype_csv(tasks: dict, output_path: Path) -> None:
    """Write configs/tasktype_consolidated.csv."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for task_name, params in sorted(tasks.items()):
        rows.append({
            "TYPE": task_name.upper(),
            "TR": params["tr"],
            "SKIP": params["skip"],
            "SMOOTHING": params["smoothing"],
            "NUMVOL": params["num_volumes"],
            "NUMECHOS": params["num_echos"],
        })

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["TYPE", "TR", "SKIP", "SMOOTHING", "NUMVOL", "NUMECHOS"])
        writer.writeheader()
        writer.writerows(rows)

    log.info("  Written: %s (%d task types)", output_path, len(rows))


# ---------------------------------------------------------------------------
# Generate scanlist CSV
# ---------------------------------------------------------------------------

SCANLIST_COLUMNS = [
    "SUBJID", "SESSION_ID", "Analyze", "BLD", "TYPE", "ANAT",
    "FMAP_MAG", "FMAP_PHASE", "FMAP_APLR", "FMAP_PARL",
    "T2", "T2_SESSION_ID",
]


def generate_scanlist_csv(
    sub_data: dict,
    iproc_dir: Path,
    output_path: Path,
) -> None:
    """Write scanlist_{sub}.csv for one subject."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sub_label = sub_data["sub_label"]
    t1_sel = sub_data["t1_selection"]
    sessions = sub_data["sessions"]

    rows = []

    for ses_label in sorted(sessions.keys()):
        ses_data = sessions[ses_label]
        bolds = ses_data["bold"]
        fmaps_mag = ses_data["fmap_mag"]
        fmaps_phase = ses_data["fmap_phase"]
        anats = ses_data["anat"]

        # Determine fieldmap SeriesNumbers for this session
        fmap_mag_sn = fmaps_mag[0]["series_number"] if fmaps_mag else 0
        fmap_phase_sn = fmaps_phase[0]["series_number"] if fmaps_phase else 0

        # Determine anatomical SeriesNumber (only if this is the T1 session)
        anat_sn = 0
        if t1_sel and t1_sel["session"] == ses_label:
            anat_sn = t1_sel["series_number"]

        # ANAT row (one per session that has a T1)
        if anats:
            for anat in anats:
                rows.append({
                    "SUBJID": sub_label,
                    "SESSION_ID": ses_label,
                    "Analyze": 1 if (t1_sel and t1_sel["session"] == ses_label and anat["run"] == t1_sel["run"]) else 0,
                    "BLD": 0,
                    "TYPE": "ANAT",
                    "ANAT": anat["series_number"],
                    "FMAP_MAG": 0,
                    "FMAP_PHASE": 0,
                    "FMAP_APLR": 0,
                    "FMAP_PARL": 0,
                    "T2": 0,
                    "T2_SESSION_ID": 0,
                })

        # BOLD rows
        analyze = 1 if (fmap_mag_sn and fmap_phase_sn) else 0
        for bold in bolds:
            rows.append({
                "SUBJID": sub_label,
                "SESSION_ID": ses_label,
                "Analyze": analyze,
                "BLD": bold["series_number"],
                "TYPE": bold["task"].upper(),
                "ANAT": anat_sn,
                "FMAP_MAG": fmap_mag_sn,
                "FMAP_PHASE": fmap_phase_sn,
                "FMAP_APLR": 0,
                "FMAP_PARL": 0,
                "T2": 0,
                "T2_SESSION_ID": 0,
            })

        # FMAP row (one per fieldmap pair per session)
        if fmaps_mag and fmaps_phase:
            rows.append({
                "SUBJID": sub_label,
                "SESSION_ID": ses_label,
                "Analyze": 1,
                "BLD": 0,
                "TYPE": "FMAP",
                "ANAT": 0,
                "FMAP_MAG": fmap_mag_sn,
                "FMAP_PHASE": fmap_phase_sn,
                "FMAP_APLR": 0,
                "FMAP_PARL": 0,
                "T2": 0,
                "T2_SESSION_ID": 0,
            })

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCANLIST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    log.info("  Written: %s (%d rows)", output_path, len(rows))


# ---------------------------------------------------------------------------
# Generate subject config (.cfg)
# ---------------------------------------------------------------------------

CFG_TEMPLATE = """\
[iproc]
SUB={sub}
BASEDIR={basedir}
OUTDIR=${{basedir}}/mri_data
LOGDIR=${{outdir}}/${{sub}}/logs
SCRATCHDIR=${{basedir}}/scratch/
MASKSDIR=${{basedir}}/mni_masks
FONT=Nimbus-Sans-Regular
CODEDIR={basedir}

[template]
MIDVOL_SESS={midvol_sess}
MIDVOL_BOLDNO={midvol_boldno:03d}
MIDVOL_VOLNO={midvol_volno}
FD_THRESH=0.4
FD_LABEL=0p4

[fmap]
# fsl_prepare_fieldmap for double-echo gradient fieldmaps
# topup for opposite-encoded spin echo fieldmaps
PREPTOOL={fmap_type}

[csv]
TASKTYPELIST=${{iproc:basedir}}/configs/tasktype_consolidated.csv
SCANLIST=${{iproc:outdir}}/${{iproc:sub}}/subject_lists/scanlist_${{iproc:sub}}.csv
CLUSTER_REQUESTS=${{iproc:basedir}}/configs/cluster_requests.csv

[fs]
# FreeSurfer subjects directory
SUBJECTS_DIR=${{iproc:basedir}}/fs/${{iproc:sub}}

[T1]
T1_SESS={t1_sess}
T1_SCAN_NO={t1_scan_no:03d}

[out_atlas]
# 111 for 1mm isotropic, 222 for 2mm isotropic
# 111 recommended for surface analysis with coarse native resolution
RESOLUTION={resolution}
MNI_RESAMP={fsldir}/data/standard/MNI152_T1_{res_mm}mm.nii.gz
MNI_RESAMP_BRAIN={fsldir}/data/standard/MNI152_T1_{res_mm}mm_brain.nii.gz
MNI_RESAMP_BRAINMASK={fsldir}/data/standard/MNI152_T1_{res_mm}mm_brain_mask.nii.gz
FS6={freesurfer_home}/subjects/fsaverage6
"""


def generate_subject_config(
    sub_data: dict,
    iproc_dir: Path,
    output_path: Path,
    resolution: int,
    fsldir: str,
    freesurfer_home: str,
) -> None:
    """Write {sub}.cfg for one subject."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sub_label = sub_data["sub_label"]
    t1_sel = sub_data["t1_selection"]
    midvol = sub_data["midvol"]
    fmap_type = sub_data["fieldmap_type"]

    res_mm = 1 if resolution == 111 else 2

    cfg = CFG_TEMPLATE.format(
        sub=sub_label,
        basedir=str(iproc_dir),
        midvol_sess=midvol["session"] if midvol else "UNKNOWN",
        midvol_boldno=midvol["bold_series_number"] if midvol else 0,
        midvol_volno=midvol["volume"] if midvol else 100,
        fmap_type=fmap_type,
        t1_sess=t1_sel["session"] if t1_sel else "UNKNOWN",
        t1_scan_no=t1_sel["series_number"] if t1_sel else 0,
        resolution=resolution,
        res_mm=res_mm,
        fsldir=fsldir,
        freesurfer_home=freesurfer_home,
    )

    with open(output_path, "w") as f:
        f.write(cfg)

    log.info("  Written: %s", output_path)


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_all(
    manifest: dict,
    iproc_dir: Path,
    fsldir: str,
    freesurfer_home: str,
) -> None:
    """Generate all iProc config files from the manifest."""
    iproc_dir = iproc_dir.resolve()
    resolution = manifest["study"]["resolution"]

    # 1. tasktype_consolidated.csv
    log.info("=== Generating tasktype_consolidated.csv ===")
    generate_tasktype_csv(
        manifest["tasks"],
        iproc_dir / "configs" / "tasktype_consolidated.csv",
    )

    # 2. Per-subject files
    for sub_name, sub_data in sorted(manifest["subjects"].items()):
        sub_label = sub_data["sub_label"]
        log.info("=== Generating config for %s ===", sub_name)

        sub_lists_dir = iproc_dir / "mri_data" / sub_label / "subject_lists"

        generate_scanlist_csv(
            sub_data,
            iproc_dir,
            sub_lists_dir / f"scanlist_{sub_label}.csv",
        )

        generate_subject_config(
            sub_data,
            iproc_dir,
            sub_lists_dir / f"{sub_label}.cfg",
            resolution=resolution,
            fsldir=fsldir,
            freesurfer_home=freesurfer_home,
        )

    log.info("")
    log.info("=== Generation complete ===")
    log.info("Next steps:")
    log.info("  1. Review generated files in %s/mri_data/", iproc_dir)
    log.info("  2. Run iProc setup stage for each subject:")
    log.info("     iProc.py -c <config.cfg> -s setup --bids /path/to/bids/sub-XXX --executor local")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate iProc configs from a BIDS manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("manifest", type=Path, help="Path to manifest.yaml from bids_discover.py")
    parser.add_argument("--iproc-dir", type=Path, required=True,
                        help="Path to iProc installation directory")
    parser.add_argument("--fsldir", type=str, default="/opt/fsl-5.0.10",
                        help="FSLDIR path (default: /opt/fsl-5.0.10 for container)")
    parser.add_argument("--freesurfer-home", type=str, default="/opt/freesurfer-6.0.0",
                        help="FREESURFER_HOME path (default: /opt/freesurfer-6.0.0 for container)")

    args = parser.parse_args()

    if not args.manifest.exists():
        log.error("Manifest not found: %s", args.manifest)
        sys.exit(1)

    with open(args.manifest) as f:
        manifest = yaml.safe_load(f)

    generate_all(
        manifest,
        args.iproc_dir,
        fsldir=args.fsldir,
        freesurfer_home=args.freesurfer_home,
    )


if __name__ == "__main__":
    main()
