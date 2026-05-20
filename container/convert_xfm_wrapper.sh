#!/bin/bash
# Wrapper around FSL 5.0.10 convert_xfm.  FSL 5.0.10 writes -omat output in
# C99 hex-float format (0x1.abcdp+0), and the rest of FSL parses these as
# 0.0 — producing all-zero matrices and NEWMAT::SingularException.  This
# wrapper runs the real binary then post-processes any -omat target file
# to canonical decimal.
#
# Bind-mounted over /opt/fsl-5.0.10/bin/convert_xfm at runtime; the real
# binary is bind-mounted alongside at /opt/.fsl_orig/convert_xfm.

set -u

"/opt/.fsl_orig/convert_xfm" "$@"
ret=$?

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
    sys.exit(0)
with open(fn, 'w') as f:
    for row in rows:
        f.write(' '.join(f'{v:.10f}' for v in row) + '\n')
PY
    fi
    prev="$arg"
done

exit $ret
