#!/usr/bin/env -S python3 -u

import os
import re
import sys
import json
import shutil
import logging
import argparse as ap
import tempfile as tf
import subprocess as sp
# Ensure the iProc package root is on sys.path when run as a subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import iproc.commons as commons

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main():
    parser = ap.ArgumentParser()
    parser.add_argument('--input',
                        help='Input BIDS file')
    parser.add_argument('--output',
        help='Output destination for floated/reorient/skipped output file')
    parser.add_argument('--sec-base',
        help='Basename for .sec files')
    parser.add_argument('--skip', type=int,
        help='Volumes to skip')
    parser.add_argument('--num-vols', type=int,
        help='Volumes to keep (after skipped)')
    parser.add_argument('--work-dir',
        help='Working directory')
    parser.add_argument('--num-echos',
        help='Number of echos')
    args = parser.parse_args()
    
    bids_input = os.path.expanduser(args.input)
    # Resolve symlinks so FSL can read git-annex objects; keep bids_input for JSON sidecar lookup
    args.input = os.path.realpath(bids_input)
    args.output = os.path.expanduser(args.output)

    os.makedirs(args.work_dir, exist_ok=True)

    # create a temporary directory for this process
    tempd = tf.mkdtemp(dir=args.work_dir)
    logger.info(f'created temporary working directory: {tempd}')
    os.chdir(tempd)

    # force the input file to float
    forced = os.path.join(tempd, 'forced')
    force_dt(args.input, forced, dtype='float')

    # force orientation to RADIOLOGICAL
    reoriented = os.path.join(tempd, 'reoriented')
    forceorient(forced, reoriented)

    # remove volumes from beginning of file
    skipped = os.path.join(tempd, 'skipped')
    roi(reoriented, skipped, begin=args.skip, end=args.num_vols)

    # move files to final destination
    logger.info(f'moving {skipped}.nii.gz to final destination {args.output}')
    shutil.move(f'{skipped}.nii.gz', args.output)

    # copy BIDS json file to output directory; use bids_input (not realpath) so the
    # JSON sidecar is found alongside the BIDS NIfTI, not inside the git-annex object tree
    src = translate_json(bids_input, args.sec_base, args.num_echos)

    if int(args.num_echos) == 1:
        dst = os.path.join(args.output, f'{args.sec_base}.json')
    else:
        #dst = os.path.join(args.output, f'{args.sec_base}_echo{nifti_basename[-1]}.json')
        dst = re.sub(r'.nii.gz', '.json', args.output)
    logger.info(f'copying {src} to {dst}')
    shutil.copyfile(src, dst)

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
    # I dont think this is currently working
    if stdout.strip().upper() == orientation.upper():
        logger.info(f'{input} is already in orientation {stdout}')
        #logger.info(f'symlinking {input} to {output}')
        #os.symlink(f'{input}.nii.gz', f'{output}.nii.gz')
        logger.info(f'renaming {input} to {output}')
        shutil.move(f'{input}.nii.gz', f'{output}.nii.gz')
        return
    logger.info(f'orientation of {input}.nii.gz is {stdout}')
    logger.info(f'naming swaporient output file {input}.nii.gz to {output}.nii.gz')
    #shutil.copy2(f'{input}.nii.gz', f'{output}.nii.gz')
    shutil.move(f'{input}.nii.gz', f'{output}.nii.gz')
    cmd = [
        'fslorient',
        '-swaporient',
        output
    ]
    logger.info(cmd)
    sp.check_output(cmd)
    if not os.path.exists(f'{output}.nii.gz'):
        raise FileNotFoundError(f'{output}.nii.gz')


def roi(input, output, begin, end):
    if not begin:
        logger.info(f'user does not want any volumes skipped from {input}.nii.gz')
        logger.info(f'renaming {input} to {output}')
        shutil.move(f'{input}.nii.gz', f'{output}.nii.gz')
        #logger.info(f'symlinking {input}.nii.gz to {output}.nii.gz')
        #os.symlink(input, output)
        return
    cmd = [
        'fslroi',
        input,
        output,
        str(begin),
        str(end)
    ]
    logger.info(cmd)
    stdout = commons.check_output(cmd)
    if not os.path.exists(f'{output}.nii.gz'):
        logger.critical(stdout)
        raise FileNotFoundError(f'{output}.nii.gz')


def translate_json(input, fname_base, numechos):
    nifti_basename = re.match('^(.*).nii(.gz)?$', input).group(1)
    if not nifti_basename:
        raise ValueError(f'{input} does not end with .nii or .nii.gz')
    json_name = f'{nifti_basename}.json'
    with open(json_name) as j:
        scan_data = json.load(j)
        echoTime = scan_data['EchoTime']
        dwellTime = scan_data['EffectiveEchoSpacing']
        # not going to use here, but want to make sure it's in json
        phase_direction = scan_data['PhaseEncodingDirection']

    if int(numechos) == 1:
        echoTime_fname = f'{fname_base}_echoTime.sec'
        dwellTime_fname = f'{fname_base}_dwellTime.sec'
    else:
        thisechonum = int(nifti_basename[-6]) # 'echo1_bold'
        echoTime_fname = f'{fname_base}_echoTime_e{thisechonum}.sec'
        dwellTime_fname = f'{fname_base}_dwellTime_e{thisechonum}.sec'

    with open(echoTime_fname, 'w') as f:
        # rounding to be consistent with xnat_to_nii_gz_task
        f.write(f'{echoTime:.4f}')
        logger.info(f'{echoTime:.4f} written to {echoTime_fname}')
    with open(dwellTime_fname, 'w') as f:
        # rounding to be consistent with xnat_to_nii_gz_task
        f.write(f'{dwellTime:.5f}')
        logger.info(f'{dwellTime:.5f} written to {dwellTime_fname}')
    return json_name


if __name__ == '__main__':
    main()

