#!/usr/bin/env -S python3 -u

import os
import sys
import shutil
import logging
import argparse as ap
import tempfile as tf 
import subprocess as sp
import iproc.commons as commons

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def main():
    parser = ap.ArgumentParser()
    parser.add_argument('--input',
        help='Input BIDS file')
    parser.add_argument('--raw-output',
        help='Output destination')
    parser.add_argument('--reorient-output',
        help='Output reoriented file')
    parser.add_argument('--work-dir', 
        help='Working directory')
    args = parser.parse_args()
    
    args.input = os.path.realpath(os.path.expanduser(args.input))
    args.raw_output = os.path.expanduser(args.raw_output)

    raw_basename = os.path.basename(args.raw_output)
    reoriented_basename = os.path.basename(args.reorient_output)

    if not os.path.exists(args.work_dir):
        os.makedirs(args.work_dir)

    # create a temporary directory for this process
    tempd = tf.mkdtemp(dir=args.work_dir)
    logger.info(f'created temporary working directory: {tempd}')
    os.chdir(tempd)

    # force the input file to float
    forced = os.path.join(tempd, raw_basename)
    force_dt(args.input, forced, dtype='float')

    # force orientation to RADIOLOGICAL
    reoriented = os.path.join(tempd, reoriented_basename)
    #forceorient(forced, reoriented)
    #reorient(forced, reoriented, dims=['-z', '-x', 'y'])
    shutil.copy2(forced, reoriented)

    # move files to final destination
    logger.info(f'moving {forced} to {args.raw_output}')
    shutil.move(forced, args.raw_output)
    logger.info(f'moving {reoriented} to {args.reorient_output}')
    shutil.move(reoriented, args.reorient_output)

    # remove the temporary directory
    shutil.rmtree(tempd)

def force_dt(input, output, dtype='float'):    
    cmd = [
        'fslmaths',
        input,
        output,
        '-odt', dtype
    ]
    logger.info(cmd)
    commons.check_output(cmd)

def forceorient(input, output, orientation='RADIOLOGICAL'):
    cmd = [
        'fslorient',
        '-getorient',
        input
    ]
    logger.info(cmd)
    stdout = sp.check_output(cmd).decode('utf-8')
    if stdout.strip().upper() == orientation.upper():
        logger.info(f'orientation of {input} is already in orientation {orientation}')
        logger.info(f'symlinking {input} to {output}')
        os.symlink(input, output)
        return
    logger.info(f'copying {input} to {output}')
    shutil.copy2(f'{input}', f'{output}')
    cmd = [
        'fslorient',
        '-swaporient',
        output
    ]
    logger.info(cmd)
    sp.check_output(cmd)

def reorient(input, output, dims):
    cmd = [
        'fslswapdim',
        input
    ]
    cmd.extend(dims)
    cmd.append(output)
    logger.info(cmd)
    commons.check_output(cmd)

if __name__ == '__main__':
    main()
