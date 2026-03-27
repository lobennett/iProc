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

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def run(cmd):
    """Run a command, log it, and raise on failure."""
    logger.info(sp.list2cmdline(cmd))
    sp.check_call(cmd)


def main():
    parser = ap.ArgumentParser('Import field map files from BIDS')
    parser.add_argument('--input-fmapm', nargs='+', default=[],
        help='Input BIDS magnitude field map files')
    parser.add_argument('--input-fmapp', nargs='+', default=[],
        help='Input BIDS phasediff field map files')
    parser.add_argument('--output-fmapm',
        help='Output fieldmap magnitude file')
    parser.add_argument('--output-fmapp',
        help='Output fieldmap phasediff file')
    parser.add_argument('--output-fieldmap',
        help='Output fieldmap file')
    parser.add_argument('--work-dir',
        help='Working directory')
    parser.add_argument('--output-maskcopy',
        help='Copy of fieldmap mag_img_brain_mask file for QC PDF')
    args = parser.parse_args()

    if not os.path.exists(args.work_dir):
        os.makedirs(args.work_dir)

    fmapm_basename = os.path.basename(args.output_fmapm)
    fmapm_prefix = re.sub('.nii(.gz)?', '', fmapm_basename)

    # create a temporary directory for this process
    tempd = tf.mkdtemp(dir=args.work_dir)
    logger.info(f'created temporary working directory: {tempd}')
    os.chdir(tempd)

    # copy or merge magnitude image(s)
    fmapm = os.path.join(tempd, os.path.basename(args.output_fmapm))
    merge(args.input_fmapm, fmapm)

    # copy or merge phasediff image(s)
    fmapp = os.path.join(tempd, os.path.basename(args.output_fmapp))
    merge(args.input_fmapp, fmapp)

    # extract brain from magnitude image
    fmapm_bet = os.path.join(tempd, f'{fmapm_prefix}_brain')
    brain_extract(fmapm, fmapm_bet)

    # erode the brain mask slightly
    fmapm_eroded = os.path.join(tempd, f'{fmapm_prefix}_brain_ero.nii.gz')
    erode(fmapm_bet, fmapm_eroded)

    # Read EchoTimeDifference and Manufacturer from the phasediff JSON sidecar
    delta_te = 2.46  # default (Siemens)
    scanner = 'SIEMENS'
    for inp in args.input_fmapp:
        candidate = re.sub(r'\.nii(\.gz)?$', '.json', inp)
        if os.path.exists(candidate):
            with open(candidate) as f:
                js = json.load(f)
            if 'EchoTimeDifference' in js:
                delta_te = js['EchoTimeDifference'] * 1000  # seconds → ms
                logger.info(f'EchoTimeDifference from JSON: {delta_te} ms')
            if 'Manufacturer' in js:
                mfr = js['Manufacturer'].upper()
                if 'GE' in mfr:
                    scanner = 'GE'
                elif 'PHILIPS' in mfr:
                    scanner = 'PHILIPS'
                logger.info(f'Scanner manufacturer: {scanner}')
            break

    # prepare the field map
    fieldmap = os.path.join(tempd, os.path.basename(args.output_fieldmap))
    prepare_fieldmap((fmapp, fmapm_eroded), fieldmap, scanner=scanner, delta_te=delta_te)

    # move derived files to final destination
    logger.info('moving %s to %s', fmapm, args.output_fmapm)
    shutil.move(fmapm, args.output_fmapm)
    logger.info('moving %s to %s', fmapp, args.output_fmapp)
    shutil.move(fmapp, args.output_fmapp)
    logger.info('moving %s to %s', fieldmap, args.output_fieldmap)
    shutil.move(fieldmap, args.output_fieldmap)

    # also move some intermediate derived files
    dirname = os.path.dirname(args.output_fmapm)
    _dest = os.path.join(dirname, f'{os.path.basename(fmapm_bet)}.nii.gz')
    logger.info(f'moving {fmapm_bet}.nii.gz to {_dest}')
    shutil.move(f'{fmapm_bet}.nii.gz', _dest)
    _dest = os.path.join(dirname, f'{os.path.basename(fmapm_bet)}_mask.nii.gz')
    logger.info(f'moving {fmapm_bet}_mask.nii.gz to {_dest}')
    shutil.move(f'{fmapm_bet}_mask.nii.gz', _dest)
    _dest = os.path.join(dirname, os.path.basename(fmapm_eroded))
    logger.info(f'moving {fmapm_eroded} to {_dest}')
    shutil.move(fmapm_eroded, _dest)

    # copy the output mag_img_brain_mask file for use in QC PDF
    dirname = os.path.dirname(args.output_fmapm)
    fmapm_brainmask = os.path.join(dirname, f'{fmapm_prefix}_brain_mask')
    fmapm_brainmask_copy = os.path.basename(args.output_maskcopy)
    logger.info(f'copying {fmapm_brainmask}.nii.gz to {fmapm_brainmask_copy}')
    shutil.copy(f'{fmapm_brainmask}.nii.gz', fmapm_brainmask_copy)

    # remove the temporary directory
    logger.info(f'removing temporary directory {tempd}')
    shutil.rmtree(tempd)


def merge(input, output):
    if not input:
        raise ValueError('merge function input is empty')
    if len(input) == 1:
        input = input.pop()
        logger.info('copying {0} to {1}'.format(input, output))
        if os.path.exists(output):
            return
        shutil.copy2(input, output)
        return
    cmd = ['fslmerge', '-t', output]
    cmd.extend(input)
    run(cmd)


def brain_extract(input, output):
    run(['bet2', input, output, '-m'])


def erode(input, output, invert=True):
    run(['fslmaths', input, '-ero', output])


def prepare_fieldmap(input, output, scanner='SIEMENS', delta_te=2.46):
    fmapp, fmapm_eroded = input
    run(['fsl_prepare_fieldmap', scanner, fmapp, fmapm_eroded, output, str(delta_te)])


if __name__ == '__main__':
    main()
