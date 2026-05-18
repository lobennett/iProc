#!/bin/bash
# run_subjects.sh — Submit iProc jobs for each subject listed in a text file.
#
# Usage:
#   ./run_subjects.sh subjects.txt <stage> [options]
#
# Arguments:
#   subjects.txt   — One subject label per line (e.g. s03, s10). Lines starting
#                    with # are ignored. Blank lines are ignored.
#   stage          — iProc stage: setup, bet, unwarp_motioncorrect_align,
#                    T1_warp_and_mask, combine_and_apply_warp, filter_and_project
#
# Options:
#   --bids-root PATH   BIDS dataset root (required for setup stage)
#   --iproc-dir PATH   iProc output directory (default: /scratch/users/logben/discovery_bids/derivatives/iproc; or $IPROC_DIR env)
#   --container PATH   Path to iproc.sif (default: <iproc-code>/container/iproc.sif; or $CONTAINER env)
#   --partition NAME   SLURM partition (default: normal)
#   --time HH:MM:SS    Wall time (default: 08:00:00)
#   --mem SIZE         Memory (default: 64G)
#   --cpus N           CPUs per task (default: 16)
#   --dry-run          Print sbatch commands without submitting
#
# Example:
#   ./run_subjects.sh subjects_discovery.txt setup --bids-root /scratch/users/logben/discovery_bids
#   ./run_subjects.sh subjects_discovery.txt bet
#   ./run_subjects.sh subjects_discovery.txt unwarp_motioncorrect_align

set -euo pipefail

# ── Defaults ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IPROC_CODE="$(dirname "$SCRIPT_DIR")"
IPROC_DIR="${IPROC_DIR:-/scratch/users/logben/discovery_bids/derivatives/iproc}"
CONTAINER="${CONTAINER:-${IPROC_CODE}/container/iproc.sif}"
BIDS_ROOT=""
PARTITION="normal"
TIME="08:00:00"
MEM="64G"
CPUS=16
DRY_RUN=false

# ── Parse args ──
if [[ $# -lt 2 ]]; then
    echo "Usage: $0 subjects.txt <stage> [options]"
    echo "Run '$0 --help' for details."
    exit 1
fi

SUBJECTS_FILE="$1"
STAGE="$2"
shift 2

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bids-root)    BIDS_ROOT="$2"; shift 2 ;;
        --iproc-dir)    IPROC_DIR="$2"; shift 2 ;;
        --container)    CONTAINER="$2"; shift 2 ;;
        --partition)    PARTITION="$2"; shift 2 ;;
        --time)         TIME="$2"; shift 2 ;;
        --mem)          MEM="$2"; shift 2 ;;
        --cpus)         CPUS="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --help|-h)
            head -35 "$0" | tail -33
            exit 0 ;;
        *)
            echo "Unknown option: $1"
            exit 1 ;;
    esac
done

# ── Validate ──
if [[ ! -f "$SUBJECTS_FILE" ]]; then
    echo "ERROR: Subjects file not found: $SUBJECTS_FILE"
    exit 1
fi

if [[ "$STAGE" == "setup" ]] && [[ -z "$BIDS_ROOT" ]]; then
    echo "ERROR: --bids-root is required for the setup stage"
    exit 1
fi

if [[ ! -f "$CONTAINER" ]] && [[ "$DRY_RUN" == "false" ]]; then
    echo "ERROR: Container not found: $CONTAINER"
    exit 1
fi

VALID_STAGES="setup bet unwarp_motioncorrect_align T1_warp_and_mask combine_and_apply_warp filter_and_project"
if ! echo "$VALID_STAGES" | grep -qw "$STAGE"; then
    echo "ERROR: Invalid stage '$STAGE'"
    echo "Valid stages: $VALID_STAGES"
    exit 1
fi

# ── Read subjects ──
SUBJECTS=()
while IFS= read -r line; do
    # Strip whitespace, skip blanks and comments
    line=$(echo "$line" | xargs)
    [[ -z "$line" ]] && continue
    [[ "$line" == \#* ]] && continue
    SUBJECTS+=("$line")
done < "$SUBJECTS_FILE"

if [[ ${#SUBJECTS[@]} -eq 0 ]]; then
    echo "ERROR: No subjects found in $SUBJECTS_FILE"
    exit 1
fi

echo "============================================"
echo "  iProc Batch Submission"
echo "  Stage: $STAGE"
echo "  Subjects: ${#SUBJECTS[@]}"
echo "  Container: $CONTAINER"
echo "  iProc code: $IPROC_CODE"
echo "  iProc output: $IPROC_DIR"
[[ -n "$BIDS_ROOT" ]] && echo "  BIDS root: $BIDS_ROOT"
echo "============================================"
echo ""

# ── Submit jobs ──
for sub in "${SUBJECTS[@]}"; do
    CONFIG="${IPROC_DIR}/mri_data/${sub}/subject_lists/${sub}.cfg"
    JOB_NAME="iproc_${STAGE}_${sub}"
    LOG_DIR="${IPROC_DIR}/mri_data/${sub}/logs"

    # Build the BIDS flag for setup stage
    BIDS_FLAG=""
    if [[ "$STAGE" == "setup" ]] && [[ -n "$BIDS_ROOT" ]]; then
        BIDS_FLAG="--bids ${BIDS_ROOT}/sub-${sub}"
    fi

    SBATCH_CMD="sbatch \
        --job-name=${JOB_NAME} \
        --partition=${PARTITION} \
        --time=${TIME} \
        --mem=${MEM} \
        --cpus-per-task=${CPUS} \
        --output=${LOG_DIR}/slurm_${STAGE}_%j.log \
        --error=${LOG_DIR}/slurm_${STAGE}_%j.err \
        --wrap=\"apptainer exec \
            --bind /oak:/oak,/scratch:/scratch \
            ${CONTAINER} \
            bash -c 'set -e && \
                     source /opt/iproc-venv/bin/activate && \
                     cd ${IPROC_CODE} && \
                     pip install -e . 2>&1 | tail -1 && \
                     mkdir -p ${LOG_DIR} && \
                     echo Running: python iProc.py -c ${CONFIG} -s ${STAGE} ${BIDS_FLAG} --executor local && \
                     python iProc.py -c ${CONFIG} -s ${STAGE} ${BIDS_FLAG} --executor local'\""

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] $sub:"
        echo "  $SBATCH_CMD"
        echo ""
    else
        # Create log dir
        mkdir -p "$LOG_DIR" 2>/dev/null || true

        echo "Submitting ${sub} (${STAGE})..."
        eval "$SBATCH_CMD"
    fi
done

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
    echo "Dry run complete. No jobs submitted."
else
    echo "Submitted ${#SUBJECTS[@]} jobs. Monitor with: squeue -u \$USER"
fi
