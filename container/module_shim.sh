#!/bin/bash
# module_shim.sh — Drop-in replacement for Lmod's `module` command inside
# the iProc Apptainer container.  Handles only `module load fsl/<version>*`
# patterns, which is all iProc needs.  Every other module command is a no-op.
#
# Sourced automatically via BASH_ENV and /etc/profile.d/ so that both
# interactive shells and Python subprocess(shell=True) calls pick it up.

module() {
    local action="$1"
    shift

    if [[ "$action" != "load" ]]; then
        return 0
    fi

    local spec="$1"

    case "$spec" in
        fsl/4.0.3*)
            export FSLDIR=/opt/fsl-4.0.3
            ;;
        fsl/5.0.4*)
            export FSLDIR=/opt/fsl-5.0.4
            ;;
        fsl/5.0.10*)
            export FSLDIR=/opt/fsl-5.0.10
            ;;
        fsl/6.0.1*)
            export FSLDIR=/opt/fsl-6.0.1
            ;;
        *)
            # All other module loads are no-ops in the container
            return 0
            ;;
    esac

    # Update PATH: remove any existing FSL bin dirs, prepend the new one
    local new_path=""
    local IFS_OLD="$IFS"
    IFS=":"
    for p in $PATH; do
        case "$p" in
            /opt/fsl-*/bin) ;;  # skip old FSL entries
            *) new_path="${new_path:+${new_path}:}${p}" ;;
        esac
    done
    IFS="$IFS_OLD"
    export PATH="${FSLDIR}/bin:${new_path}"

    # Source FSL setup if it exists
    if [[ -f "${FSLDIR}/etc/fslconf/fsl.sh" ]]; then
        source "${FSLDIR}/etc/fslconf/fsl.sh"
    fi
}

export -f module
