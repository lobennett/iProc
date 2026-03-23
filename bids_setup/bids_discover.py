# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "nibabel>=5.0",
#     "pyyaml>=5.0",
# ]
# ///
"""
bids_discover.py — Scan a BIDS dataset and produce an editable YAML manifest
for iProc configuration generation.

Usage:
    uv run bids_discover.py /path/to/bids_root \
        --output manifest.yaml \
        --skip 7 \
        --smoothing 6 \
        --resolution 222

The manifest is the checkpoint between discovery and generation.
Review it, edit T1 selections or exclude sessions, then pass to bids_generate.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import nibabel as nib
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BIDS filename parsing
# ---------------------------------------------------------------------------

BOLD_RE = re.compile(
    r"sub-(?P<sub>[^_]+)"
    r"_ses-(?P<ses>[^_]+)"
    r"_task-(?P<task>[^_]+)"
    r"(?:_run-(?P<run>\d+))?"
    r"(?:_echo-(?P<echo>\d+))?"
    r"_bold\.nii\.gz$"
)

FMAP_MAG_RE = re.compile(
    r"sub-(?P<sub>[^_]+)"
    r"_ses-(?P<ses>[^_]+)"
    r"(?:_run-(?P<run>\d+))?"
    r"_magnitude(?P<idx>[12])?\.nii\.gz$"
)

FMAP_PHASE_RE = re.compile(
    r"sub-(?P<sub>[^_]+)"
    r"_ses-(?P<ses>[^_]+)"
    r"(?:_run-(?P<run>\d+))?"
    r"_(?:fieldmap|phasediff|phase(?P<idx>[12]))\.nii\.gz$"
)

ANAT_RE = re.compile(
    r"sub-(?P<sub>[^_]+)"
    r"_ses-(?P<ses>[^_]+)"
    r"(?:_run-(?P<run>\d+))?"
    r"_T1w\.nii\.gz$"
)


def read_json(nii_path: Path) -> dict:
    """Read the JSON sidecar for a NIfTI file."""
    json_path = nii_path.with_suffix("").with_suffix(".json")
    if not json_path.exists():
        # Handle .nii.gz → .json
        name = nii_path.name.replace(".nii.gz", ".json")
        json_path = nii_path.parent / name
    if not json_path.exists():
        log.warning("No JSON sidecar for %s", nii_path.name)
        return {}
    with open(json_path) as f:
        return json.load(f)


def get_nvols(nii_path: Path) -> int:
    """Get number of volumes from NIfTI header without loading data."""
    try:
        img = nib.load(str(nii_path))
        shape = img.shape
        return shape[3] if len(shape) > 3 else 1
    except Exception as e:
        log.warning("Could not read %s: %s", nii_path.name, e)
        return 0


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_subject(bids_root: Path, sub_dir: Path, skip: int, smoothing: float) -> dict:
    """Discover all sessions, tasks, fieldmaps, and anatomicals for one subject."""
    sub_id = sub_dir.name  # e.g. "sub-s03"
    sub_label = sub_id.replace("sub-", "")

    sessions: dict[str, dict] = {}
    task_params: dict[str, dict] = {}  # task_name → {tr, nvols, nechos, ...}

    for ses_dir in sorted(sub_dir.iterdir()):
        if not ses_dir.is_dir() or not ses_dir.name.startswith("ses-"):
            continue

        ses_label = ses_dir.name.replace("ses-", "")
        ses_data: dict[str, Any] = {
            "anat": [],
            "bold": [],
            "fmap_mag": [],
            "fmap_phase": [],
        }

        # --- Anatomicals ---
        anat_dir = ses_dir / "anat"
        if anat_dir.is_dir():
            for f in sorted(anat_dir.glob("*.nii.gz")):
                m = ANAT_RE.match(f.name)
                if not m:
                    continue
                js = read_json(f)
                ses_data["anat"].append({
                    "file": str(f.relative_to(bids_root)),
                    "run": int(m.group("run") or 1),
                    "series_number": js.get("SeriesNumber", 0),
                })

        # --- Fieldmaps ---
        fmap_dir = ses_dir / "fmap"
        if fmap_dir.is_dir():
            for f in sorted(fmap_dir.glob("*.nii.gz")):
                mag_m = FMAP_MAG_RE.match(f.name)
                phase_m = FMAP_PHASE_RE.match(f.name)

                if mag_m:
                    js = read_json(f)
                    ses_data["fmap_mag"].append({
                        "file": str(f.relative_to(bids_root)),
                        "run": int(mag_m.group("run") or 1),
                        "series_number": js.get("SeriesNumber", 0),
                    })
                elif phase_m:
                    js = read_json(f)
                    ses_data["fmap_phase"].append({
                        "file": str(f.relative_to(bids_root)),
                        "run": int(phase_m.group("run") or 1),
                        "series_number": js.get("SeriesNumber", 0),
                        "echo_time_diff": js.get("EchoTimeDifference", None),
                    })

        # --- Functional ---
        func_dir = ses_dir / "func"
        if func_dir.is_dir():
            # Group by task+run to count echoes
            task_run_echoes: dict[str, list] = defaultdict(list)

            for f in sorted(func_dir.glob("*_bold.nii.gz")):
                m = BOLD_RE.match(f.name)
                if not m:
                    continue

                task = m.group("task")
                run = int(m.group("run") or 1)
                echo = int(m.group("echo") or 1)
                key = f"{task}_run-{run}"

                task_run_echoes[key].append({
                    "file": str(f.relative_to(bids_root)),
                    "task": task,
                    "run": run,
                    "echo": echo,
                    "nii_path": f,
                })

            for key, echoes in sorted(task_run_echoes.items()):
                first = echoes[0]
                task = first["task"]
                run = first["run"]
                nii_path = first["nii_path"]

                js = read_json(nii_path)
                nvols_total = get_nvols(nii_path)
                nvols = max(0, nvols_total - skip)
                nechos = len(echoes)

                series_number = js.get("SeriesNumber", 0)
                tr = js.get("RepetitionTime", 0)
                echo_time = js.get("EchoTime", 0)
                eff_echo_spacing = js.get("EffectiveEchoSpacing", 0)
                phase_dir = js.get("PhaseEncodingDirection", "")

                ses_data["bold"].append({
                    "task": task,
                    "run": run,
                    "series_number": series_number,
                    "num_volumes_total": nvols_total,
                    "num_volumes": nvols,
                    "num_echos": nechos,
                    "tr": round(tr, 4) if tr else None,
                    "echo_time": round(echo_time, 6) if echo_time else None,
                    "effective_echo_spacing": round(eff_echo_spacing, 8) if eff_echo_spacing else None,
                    "phase_encoding_direction": phase_dir,
                })

                # Accumulate task parameters (use first occurrence as canonical)
                task_upper = task.upper()
                if task_upper not in task_params:
                    task_params[task_upper] = {
                        "task_bids_name": task,
                        "tr": round(tr, 4) if tr else None,
                        "skip": skip,
                        "smoothing": smoothing,
                        "num_volumes": nvols,
                        "num_echos": nechos,
                    }

        sessions[ses_label] = ses_data

    # --- T1 selection: pick the LATEST session with a T1w ---
    t1_selection = None
    for ses_label in sorted(sessions.keys(), reverse=True):
        anats = sessions[ses_label]["anat"]
        if anats:
            # If multiple T1s in same session, pick last run
            best = sorted(anats, key=lambda a: a["run"])[-1]
            t1_selection = {
                "session": ses_label,
                "run": best["run"],
                "series_number": best["series_number"],
                "file": best["file"],
            }
            break

    if t1_selection is None:
        log.warning("No T1w found for %s", sub_id)

    # --- MIDVOL target: first session, first BOLD run ---
    midvol = None
    for ses_label in sorted(sessions.keys()):
        bolds = sessions[ses_label]["bold"]
        if bolds:
            first_bold = bolds[0]
            midvol_vol = first_bold["num_volumes"] // 2
            midvol = {
                "session": ses_label,
                "task": first_bold["task"],
                "run": first_bold["run"],
                "bold_series_number": first_bold["series_number"],
                "volume": midvol_vol,
            }
            break

    if midvol is None:
        log.warning("No BOLD data found for %s", sub_id)

    # --- Detect fieldmap type ---
    fmap_type = None
    for ses_label, ses_data in sessions.items():
        if ses_data["fmap_mag"] and ses_data["fmap_phase"]:
            fmap_type = "fsl_prepare_fieldmap"
            break

    if fmap_type is None:
        log.warning("Could not detect fieldmap type for %s", sub_id)

    return {
        "sub_label": sub_label,
        "sessions": sessions,
        "task_params": task_params,
        "t1_selection": t1_selection,
        "midvol": midvol,
        "fieldmap_type": fmap_type or "fsl_prepare_fieldmap",
    }


def discover_dataset(
    bids_root: Path,
    skip: int,
    smoothing: float,
    resolution: int,
    subjects: list[str] | None = None,
) -> dict:
    """Discover the entire BIDS dataset."""
    bids_root = bids_root.resolve()

    if not bids_root.is_dir():
        log.error("BIDS root does not exist: %s", bids_root)
        sys.exit(1)

    sub_dirs = sorted(
        d for d in bids_root.iterdir()
        if d.is_dir() and d.name.startswith("sub-")
    )

    if subjects:
        sub_dirs = [d for d in sub_dirs if d.name in subjects or d.name.replace("sub-", "") in subjects]

    if not sub_dirs:
        log.error("No subjects found in %s", bids_root)
        sys.exit(1)

    log.info("Found %d subject(s) in %s", len(sub_dirs), bids_root)

    all_subjects = {}
    all_tasks: dict[str, dict] = {}

    for sub_dir in sub_dirs:
        log.info("Discovering %s ...", sub_dir.name)
        sub_data = discover_subject(bids_root, sub_dir, skip, smoothing)
        all_subjects[sub_dir.name] = sub_data

        # Merge task params (first occurrence wins)
        for task_name, params in sub_data["task_params"].items():
            if task_name not in all_tasks:
                all_tasks[task_name] = params

    manifest = {
        "_notes": {
            "generated_by": "bids_discover.py",
            "description": (
                "Review this manifest before running bids_generate.py. "
                "You can edit t1_selection, midvol, skip, smoothing, "
                "resolution, or set Analyze=false on specific sessions/runs."
            ),
            "design_decisions": {
                "t1_selection": "Uses the LATEST session with a T1w (rationale: earlier T1s may be low quality)",
                "midvol_target": "First session, first BOLD run, middle volume",
                "skip_volumes": f"{skip} dummy scans discarded from start of each functional run",
                "smoothing": f"{smoothing}mm FWHM (use 0 for surface-only analysis)",
                "resolution": f"{'1mm' if resolution == 111 else '2mm'} isotropic output template",
            },
        },
        "study": {
            "bids_root": str(bids_root),
            "resolution": resolution,
            "default_smoothing": smoothing,
            "default_skip": skip,
        },
        "tasks": all_tasks,
        "subjects": all_subjects,
    }

    return manifest


# ---------------------------------------------------------------------------
# Validation warnings
# ---------------------------------------------------------------------------

def validate_manifest(manifest: dict) -> list[str]:
    """Run basic sanity checks on the discovered manifest."""
    warnings = []

    for sub_name, sub_data in manifest["subjects"].items():
        if sub_data["t1_selection"] is None:
            warnings.append(f"{sub_name}: No T1w anatomical found in any session")

        if sub_data["midvol"] is None:
            warnings.append(f"{sub_name}: No BOLD data found")

        sessions = sub_data["sessions"]
        for ses_label, ses_data in sessions.items():
            bolds = ses_data["bold"]
            fmaps_mag = ses_data["fmap_mag"]
            fmaps_phase = ses_data["fmap_phase"]

            if bolds and not (fmaps_mag and fmaps_phase):
                warnings.append(
                    f"{sub_name}/ses-{ses_label}: Has {len(bolds)} BOLD run(s) "
                    f"but no fieldmap (mag={len(fmaps_mag)}, phase={len(fmaps_phase)})"
                )

            # Check SeriesNumber consistency for fieldmaps
            if fmaps_mag and fmaps_phase:
                mag_sn = fmaps_mag[0]["series_number"]
                phase_sn = fmaps_phase[0]["series_number"]
                diff = phase_sn - mag_sn
                if diff not in (1, 2) and mag_sn != 0 and phase_sn != 0:
                    warnings.append(
                        f"{sub_name}/ses-{ses_label}: Fieldmap phase SeriesNumber ({phase_sn}) "
                        f"is not magnitude+1 or +2 ({mag_sn}). iProc may reject this."
                    )

            # Check task consistency
            for bold in bolds:
                task_upper = bold["task"].upper()
                if task_upper not in manifest["tasks"]:
                    warnings.append(
                        f"{sub_name}/ses-{ses_label}: Task '{bold['task']}' not in task list"
                    )
                else:
                    expected = manifest["tasks"][task_upper]
                    if bold["num_echos"] != expected["num_echos"]:
                        warnings.append(
                            f"{sub_name}/ses-{ses_label}/{bold['task']}_run-{bold['run']}: "
                            f"echo count {bold['num_echos']} != expected {expected['num_echos']}"
                        )

    return warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Discover a BIDS dataset and produce an iProc manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("bids_root", type=Path, help="Path to BIDS dataset root")
    parser.add_argument("-o", "--output", type=Path, default=Path("manifest.yaml"),
                        help="Output manifest YAML (default: manifest.yaml)")
    parser.add_argument("--skip", type=int, default=7,
                        help="Number of dummy volumes to skip (default: 7)")
    parser.add_argument("--smoothing", type=float, default=6.0,
                        help="Smoothing kernel FWHM in mm (default: 6.0)")
    parser.add_argument("--resolution", type=int, choices=[111, 222], default=222,
                        help="Output resolution: 111=1mm, 222=2mm (default: 222)")
    parser.add_argument("--subjects", nargs="+", default=None,
                        help="Process only these subjects (e.g. sub-s03 sub-s04)")

    args = parser.parse_args()

    manifest = discover_dataset(
        args.bids_root,
        skip=args.skip,
        smoothing=args.smoothing,
        resolution=args.resolution,
        subjects=args.subjects,
    )

    # Validate
    warnings = validate_manifest(manifest)
    if warnings:
        log.warning("=== Validation Warnings ===")
        for w in warnings:
            log.warning("  %s", w)

    # Write manifest
    with open(args.output, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False, width=120)

    log.info("Manifest written to %s", args.output)
    log.info("Subjects: %d, Tasks: %d, Warnings: %d",
             len(manifest["subjects"]),
             len(manifest["tasks"]),
             len(warnings))
    log.info("")
    log.info("Next step: review the manifest, then run:")
    log.info("  uv run bids_generate.py %s --iproc-dir /path/to/iProc", args.output)


if __name__ == "__main__":
    main()
