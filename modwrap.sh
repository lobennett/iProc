#!/bin/bash
# wraps some command in an arbitrary pre- and post- command. Originally designed to change modules in and out on the fly.
# usage: modwrap.sh module load fsl/6.0.2-ncf fsl/5.0.4-ncf commandToRun.sh cmdarg1 cmdarg2 cmdarg3
set -xeou pipefail
prepcmd=$1
postcmd=$2
shift
shift

$prepcmd || true

"$@"

$postcmd || true
