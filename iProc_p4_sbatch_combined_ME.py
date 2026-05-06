#!/usr/bin/env python

# Combine warps to project BOLD data to T1 in single interpolation
## Written by R. Braga & L. DiNicola - February 2018
# originally was two scripts, one for MNI and one for subject's T1w anat. 
# combined and paralellized by hhoke

#Edited by Jenn 2024.06.12: Added echo number flag and changed the convertwarp output to .nii.gz instead of .mat (That's how it was writing it anyway!)

import shutil
import time
import os
import sys
import csv
import logging
import glob
import subprocess
import re
import socket
from subprocess import call
from argparse import ArgumentParser
import concurrent.futures as cf
from iproc.commons import execute, program, machine
import iproc.executors as executors

import numpy as np
#import matplotlib as mpl
#mpl.use('Agg')
#import matplotlib.pyplot as plt

logger = logging.getLogger(os.path.basename(__file__))
format="[%(asctime)s][%(levelname)s] - %(name)s - %(message)s"
logging.basicConfig(format=format, level=logging.DEBUG)

def convert_warpcall_MNI(fi_name):
    start=time.time()
    spacename='MNI'
    res = re.findall("MAT_(\d+)", fi_name)
    print(res)
    end_mat = os.path.join(args.scratch,"{}_TARG_WARP_{}".format(spacename, res[0]))
    # combine fieldmap warp with midvolMCtarget-to-T1 transform and T1-to-MNI transform
    template_cmd = "convertwarp --ref={TARGET} --warp2={COMB_MAT} --warp1={FMMAT} --premat={MOT_MAT} --out={END_MAT} --relout"

    cmd=template_cmd.format(
        COMB_MAT=comb_mat,
        MOT_MAT=fi_name,
        TARGET=target,
        END_MAT=end_mat,
        FMMAT=fmmat)
    print(cmd)
    summary = execute(cmd, kill=True) #should take about 30s

    if (summary.status == 0): 
        pass
    else:
        raise Exception('failed command {}'.format(' '.join(cmd)))
    stop=time.time()
    return start,stop

def convert_warpcall_anat(fi_name):
    start=time.time()
    res = re.findall("MAT_(\d+)", fi_name)
    print(res)
    comb_mat = os.path.join(args.scratch,"T1_TARG_WARP_%s" % res[0])
    # combine fieldmap warp with midvolMCtarget-to-T1 transform
    template_cmd = "convertwarp --ref={TARGET} --warp1={FMMAT} --premat={MOT_MAT} --postmat={POST_MAT} --out={COMB_MAT} --relout"

    cmd=template_cmd.format(
        COMB_MAT=comb_mat,
        MOT_MAT=fi_name,
        TARGET=target, #global
        POST_MAT=omat,
        FMMAT=fmmat) #global 
    print(cmd)
    summary = execute(cmd, kill=True) #should take about 30s

def apply_warpcall_MNI(fi_name):
    start = time.time()
    res = re.findall("time_point_(\d+).nii.gz", fi_name)
    spacename='MNI'
    end_mat = os.path.join(args.scratch,"{}_TARG_WARP_{}".format(spacename, res[0]))
    fnirt_out = os.path.join(args.scratch,"{}_TARG_FILE_{}".format(spacename, res[0]))

    template_cmd = "applywarp --ref={TARGET} --in={FNIRT_IN} --warp={END_MAT} --rel --out={FNIRT_OUT}"
    cmd=template_cmd.format(
        FNIRT_IN=fi_name,
        END_MAT=end_mat,
        FNIRT_OUT=fnirt_out,
        TARGET=target)
    print(cmd)
    summary = execute(cmd, kill=True)

    if (summary.status == 0):
        pass
    else:
        raise Exception('failed command {}'.format(' '.join(cmd)))
    stop=time.time()
    return start,stop

def apply_warpcall_anat(fi_name):
    start = time.time()
    res = re.findall("time_point_(\d+).nii.gz", fi_name)

    comb_mat = os.path.join(args.scratch,"T1_TARG_WARP_%s" % res[0])
    fnirt_out = os.path.join(args.scratch,"T1_TARG_FILE_%s" % res[0])

    template_cmd = "applywarp --ref={TARGET} --in={FNIRT_IN} --warp={COMB_MAT} --rel --out={FNIRT_OUT}"
    cmd=template_cmd.format(
        FNIRT_IN=fi_name,
        COMB_MAT=comb_mat,
        FNIRT_OUT=fnirt_out,
        TARGET=target)
    print(cmd)
    summary = execute(cmd, kill=True)

def visualize_runtimes(results,fig):
    start,stop = np.array(results).T
    fig.barh(list(range(len(start))), stop-start, left=start)
    fig.grid(axis='x')
    fig.set_ylabel("Task #")
    fig.set_xlabel("Seconds")

def multiprocessing(proc, fn, arg_list):
    with cf.ProcessPoolExecutor(proc) as ex:
        results = ex.map(fn, arg_list)
    return list(results)

def serial(fn, arg_list):
    results = [fn(a) for a in arg_list]

# argument parsing
parser = ArgumentParser(description="CSV parser and job launcher")
parser.add_argument("-m", "--mat-dir", required=True, 
    help="Path to MAT files")
parser.add_argument("-n", "--numvol", required=True, 
    help="number of time points in BOLD data")
parser.add_argument("-c", "--template-dir", required=True,
    help="template directory")
parser.add_argument("-o", "--output-dir", required=True,
    help="entire directory containing Output directory")
parser.add_argument("-s", "--subject-id", required=True,
    help="Subject ID")
parser.add_argument("-t", "--task-type", required=True,
    help="Task Type")
parser.add_argument("-x", "--session-id", required=True,
    help="Session ID")
parser.add_argument("-b", "--bold-no", required=True,
    help="Bold Number")
parser.add_argument("-d", "--destination-space", required=True,choices=["MNI","T1"],
    help="which output space")
parser.add_argument("--scratch", required=True,
    help="scratch directory to use for convert_mat output.")
parser.add_argument("-a", "--mni-atlas",  
    help="mni atlas to use.")
parser.add_argument("-e", "--echo-num", required=True, 
    help="echo number of this volume")
# TODO: no-unwarp
args = parser.parse_args()
if args.destination_space == "MNI" and not args.mni_atlas:
    parser.error("MNI --destination-space specified, but --mni-atlas not specified")

# print information about program and machine
logger.info(program(sys.argv))
logger.info(machine())

# expand any ~/ in filenames
args.mat_dir = os.path.expanduser(args.mat_dir)
args.output_dir = os.path.expanduser(args.output_dir)

# Combine warps (mcTarget-meanBOLD + meanBOLD-T1)
template_cmd = "convert_xfm -omat {OMAT} -concat {BtoC} {AtoB}"

# TODO: check output exists before executing
omat = os.path.join(args.output_dir,"%s_to_anat.mat" % args.bold_no)
atob = os.path.join(args.output_dir,"%s_to_allscans.mat" % args.bold_no)
btoc = os.path.join(args.template_dir,"%s_allscans_meanBOLD_to_T1.mat" % args.subject_id)

cmd=template_cmd.format(
    OMAT=omat,
    AtoB=atob,
    BtoC=btoc)

summary = execute(cmd, kill=True)
print(cmd)
time.sleep(2)

# declare global variables so we can easily access in parallel-run function
target = None
unwarp_dir = 'fm_unwarp{}'.format(args.bold_no)
fmmat = os.path.join(args.output_dir, unwarp_dir,"EF_UD_warp.nii.gz")
#run one or the other function by renaming in if block
convert_warpcall = None
apply_warpcall = None
if args.destination_space == "MNI":
    #MNI specific -- combine MNI and ANAT warps
    template_cmd = "convertwarp --ref={TARGET} --warp1={STD_MAT} --premat={OMAT} --out={COMB_MAT} --relout"

    # set global variables to be used by parallel steps    
    omat = os.path.join(args.output_dir,"%s_to_anat.mat" % args.bold_no)
    comb_mat = os.path.join(args.output_dir, "%s_to_MNI.nii.gz" % args.bold_no)
    target = os.path.join(args.mni_atlas)
    std_mat = os.path.join(args.template_dir,"mpr_to_mni_FNIRT.mat.nii.gz")
    
    cmd=template_cmd.format(
        COMB_MAT=comb_mat,
        TARGET=target,
        OMAT=omat,
        STD_MAT=std_mat)
    print(cmd)
    summary = execute(cmd, kill=True) 
    time.sleep(2)

    target = os.path.join(args.mni_atlas)
    convert_warpcall = convert_warpcall_MNI
    apply_warpcall = apply_warpcall_MNI
else: #assume anat
    target = os.path.join(args.template_dir,"mpr.nii.gz")
    convert_warpcall = convert_warpcall_anat
    apply_warpcall = apply_warpcall_anat

# get number of cpus
cpus = len(os.sched_getaffinity(0))
logger.info(f'there are {cpus} processors available to this task')

##merge the linear and nonlinear warps
## for ~400 individual files
volnums = [str(n) for n in range(int(args.numvol))]
out_file_names = ['MAT_{}'.format(n.zfill(4)) for n in volnums]
matfiles = [os.path.join(args.mat_dir, f) for f in out_file_names]
matfiles_exist = {f:os.path.exists(f) for f in matfiles}
if not all(matfiles_exist.values()):
    matfiles_missing = [k for k,v in list(matfiles_exist.items()) if not v]
    matfiles_join = ' '.join(matfiles_missing)
    raise Exception('Some matfiles do not exist: {}'.format(matfiles_join))
# writes to scratch to save on i/o
multiprocessing(cpus, convert_warpcall, matfiles)

#apply non-linear matrix registration to specific volume
tmpfiles = glob.glob(os.path.join(args.scratch, "time_point_*.nii.gz"))
print(tmpfiles)
multiprocessing(cpus, apply_warpcall, tmpfiles)

print((socket.getfqdn()))
print("Done!")
