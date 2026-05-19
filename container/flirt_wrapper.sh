#!/bin/bash
# Wrapper around FSL 5.0.10 flirt that post-processes any -omat output
# from C99 hex-float format (0x1.abcdp+0) into canonical decimal that
# the rest of FSL can parse.  Without this, downstream fnirt /
# convertwarp / convert_xfm / applywarp parse the hex floats as 0.0,
# producing all-zero matrices and NEWMAT::SingularException.
#
# Bind-mounted over /opt/fsl-5.0.10/bin/flirt at runtime via apptainer
# --bind; the real binary is bind-mounted alongside at
# /opt/.fsl_orig/flirt so the wrapper can call it without recursion.

set -u

"/opt/.fsl_orig/flirt" "$@"
ret=$?

# Find any -omat argument and convert its target file to decimal.
prev=""
for arg in "$@"; do
    if [ "$prev" = "-omat" ] && [ -n "$arg" ] && [ -f "$arg" ]; then
        python3 - "$arg" <<'PY'
import sys
fn = sys.argv[1]
try:
    with open(fn) as f:
        rows = [[float.fromhex(t) for t in line.split()] for line in f if line.strip()]
except (ValueError, OSError):
    # Already decimal or empty; leave alone.
    sys.exit(0)
with open(fn, 'w') as f:
    for row in rows:
        f.write(' '.join(f'{v:.10f}' for v in row) + '\n')
PY
    fi
    prev="$arg"
done

exit $ret
