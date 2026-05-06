#!/usr/bin/env python
'''
`steps.py` consists of largely refactored legacy code. 
More or less, each function in `steps.py` started its life as a standalone python script, with its own argument handling and way of interacting with the cluster. 
Now, each function largely consists of logic needed to construct individual data processing jobs. 

Each job consists of a script, located in `runscript`. These scripts are also largely refactored legacy code. 
Most are extremely inflexible and should not be run as standalone scripts in a normal use case. However, they can be run as standalone scripts for debugging purposes. These scripts are designed to log each and every subprocess used for data processing, and to fail if any subroutine fails. In addition to creating job specs, these functions create rmfile lists, which are lists of files to be destroyed, along with the last step in which they are needed.

'''
import json
import shutil
import time
import os
import sys
import csv
import re
import logging
import glob
import pickle
import subprocess as sp
import importlib
import tempfile
import datetime
import collections
import iproc.commons as commons
from iproc.bids import sanitize,split_task
from pathlib import Path

#get logger from calling script
logger = logging.getLogger(__name__)
JobSpec = commons.JobSpec

class jobConstructor(object):
    def __init__(self, conf,scans,args):
        self.conf = conf
        self.scans = scans
        self.args = args
        # TODO: remove moribund function
        self.steplog_base = os.path.join(conf.iproc.LOGDIR,'stepLog')
        self.rmfiles = {}
        self.rm_dump_filename = os.path.join(self.conf.iproc.RMFILE_DUMP, f'{self.args.stage}.crash')
        self.rm_final_filename = os.path.join(self.conf.iproc.RMFILE_DUMP, f'{self.args.stage}.final')

    def reset_steplog(self):
        # TODO: remove moribund function
        self.steplog_base = os.path.join(self.conf.iproc.LOGDIR, 'stepLog')

    def anat_from_bids(self,overwrite=True):
        stepname_base = 'anat_from_bids'
        logger.debug(stepname_base)

        self.reset_steplog()
        job_spec_list = []
        self.reset_steplog()
        sub = self.conf.iproc.SUB
        for sessionid,sess in self.scans.anat_sessions():
            ses = sessionid
            for anat_dir,anat_scan in self.scans.anats():
                run = anat_scan['BIDS_ID']
                logger.info(f'processing sub={sub}, ses={ses}, anat={run}')
                # Use glob to find the T1w file regardless of optional BIDS entities (e.g. acq-)
                anat_glob = os.path.join(
                    self.args.bids,
                    f'ses-{sanitize(ses)}/anat/sub-{sanitize(sub)}_ses-{sanitize(ses)}_*_run-{run}_T1w.nii.gz'
                )
                anat_matches = glob.glob(anat_glob)
                if not anat_matches:
                    raise IOError(f'No T1w file found matching: {anat_glob}')
                bids_anat_file = anat_matches[0]
                #scan_no is set automatically by self.scans.anats()
                run_zpad = f'{int(self.scans.scan_no):03d}'  # note that this is the ScanNumber, not the BIDS run number
                anat_basename = f'{ses}_mpr{run_zpad}'
                anat_dirname = os.path.join(self.conf.iproc.NATDIR, ses, f'{anat_dir}_{run_zpad}')
                work_dirname = os.path.join(self.conf.iproc.WORKDIR, f'ANAT_{ses}')
                dest_nii = os.path.join(anat_dirname, anat_basename + '.nii.gz')
                dest_reorient_nii = os.path.join(anat_dirname, anat_basename + '_reorient.nii.gz')
                outfiles = [dest_reorient_nii]
                if self._outfiles_skip(overwrite,outfiles):
                    continue
                #elif not self.args.no_remove_files:
                    #for outfile in outfiles:
                        #os.remove(outfile) 
                        #logging.debug(f'removed {outfile}')

                for d in [anat_dirname, work_dirname]:
                    if not os.path.exists(d):
                        os.makedirs(d)
                script = os.path.join(os.path.expanduser(self.conf.iproc.CODEDIR), 'runscript', 'anat_from_bids.py')

                cmd = [
                    script,
                    '--input', bids_anat_file,
                    '--raw-output', dest_nii,
                    '--reorient-output', dest_reorient_nii,
                    '--work-dir', work_dirname
                ]
                logger.info(sp.list2cmdline(cmd))
                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))
        self.scans.reset_default_sessionid()
        return job_spec_list

    def func_from_bids(self,overwrite=True):
        logger.debug('func_from_bids')
        job_spec_list = list()
        self.reset_steplog()
        for sessionid,sess in self.scans.sessions():
            sub = self.conf.iproc.SUB
            ses = sessionid
            for task_name,bold_scan in self.scans.tasks():
                task = self.scans.task_dict[task_name]
                bids_task_name,_ = split_task(task_name)
                numechos = task['NUMECHOS']

                run = bold_scan['BIDS_ID']
                if not run:
                    logger.debug(f'task column {task_name} is set to zero in {self.conf.csv.SCANLIST}')
                    continue

                logger.info(f'processing sub={sub}, ses={ses}, task={task_name}, run={run}')

                # Resolve the BIDS func file via glob to handle case differences between
                # the all-caps scanlist task names (e.g. REST, CUEDTS) and the actual
                # mixed-case BIDS filenames (e.g. task-rest, task-cuedTS).
                func_dir = os.path.join(self.args.bids, f'ses-{sanitize(ses)}/func')

                if int(numechos) == 1:

                    func_glob = os.path.join(func_dir, f'sub-{sanitize(sub)}_ses-{sanitize(ses)}_task-*_run-{run}_bold.nii.gz')
                    func_matches = [f for f in glob.glob(func_glob) if f.lower().count(f'task-{bids_task_name.lower()}_') == 1]
                    if not func_matches:
                        raise IOError(f'No BOLD file found matching (case-insensitive task={bids_task_name}): {func_glob}')
                    bids_func_file = func_matches[0]
                    run_zpad = f'{int(bold_scan["BLD"]):03d}'

                    task_dirname = os.path.join(self.conf.iproc.NATDIR, ses, f'{task_name}_{run_zpad}')
                    task_basename = f'{ses}_bld{run_zpad}_reorient_skip.nii.gz'
                    sec_basename = f'{ses}_bld{run_zpad}'
                    dest_nii = os.path.join(task_dirname, task_basename)
                    sec_base = os.path.join(task_dirname, sec_basename)

                    outfiles = [dest_nii,sec_base+'_echoTime.sec',sec_base+'_dwellTime.sec']
                    if self._outfiles_skip(overwrite,outfiles):
                        continue
                    #elif not self.args.no_remove_files:
                    #    for outfile in outfiles:
                    #        os.remove(outfile) 
                    #        logging.debug(f'removed {outfile}')
                    work_dirname = os.path.join(self.conf.iproc.WORKDIR, f'{task_name}_{ses}')
                    for d in [work_dirname, task_dirname]:
                        if not os.path.exists(d):
                            os.makedirs(d)
                    script = os.path.join(os.path.expanduser(self.conf.iproc.CODEDIR), 'runscript', 'func_from_bids.py')
                    cmd = [
                        script,
                        '--input', bids_func_file,
                        '--output', dest_nii,
                        '--sec-base', sec_base,
                        '--skip', task['SKIP'],
                        '--num-vol', task['NUMVOL'],
                        '--work-dir', work_dirname,
                        '--num-echos', numechos
                    ]
                    logfile_base = self._io_file_fmt(cmd)
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))
                    ### added num-echos flag for multi-echo, JS 2025.03.19 


                ### ---- MULTI_ECHO!!!!, JS 2025.03.19 ---- ###
                else:
                    for iEcho in range(1,int(numechos) + 1):
                        func_glob = os.path.join(func_dir, f'sub-{sanitize(sub)}_ses-{sanitize(ses)}_task-*_run-{run}_echo-{iEcho}_bold.nii.gz')
                        func_matches = [f for f in glob.glob(func_glob) if f.lower().count(f'task-{bids_task_name.lower()}_') == 1]
                        if not func_matches:
                            raise IOError(f'No BOLD file found matching (case-insensitive task={bids_task_name}): {func_glob}')
                        bids_func_file = func_matches[0]
                        run_zpad = f'{int(bold_scan["BLD"]):03d}'

                        task_dirname = os.path.join(self.conf.iproc.NATDIR, ses, f'{task_name}_{run_zpad}')
                        task_basename = f'{ses}_bld{run_zpad}_reorient_skip_e{iEcho}.nii.gz'
                        sec_basename = f'{ses}_bld{run_zpad}'
                        dest_nii = os.path.join(task_dirname, task_basename)
                        sec_base = os.path.join(task_dirname, sec_basename)

                        outfiles = [dest_nii,sec_base+f'_echoTime_e{iEcho}.sec',sec_base+f'_dwellTime_e{iEcho}.sec']
                        if self._outfiles_skip(overwrite,outfiles):
                            continue
                        #elif not self.args.no_remove_files:
                        #    for outfile in outfiles:
                        #        os.remove(outfile) 
                        #        logging.debug(f'removed {outfile}')
                        work_dirname = os.path.join(self.conf.iproc.WORKDIR, f'{task_name}_{ses}')
                        for d in [work_dirname, task_dirname]:
                            if not os.path.exists(d):
                                os.makedirs(d)
                        script = os.path.join(os.path.expanduser(self.conf.iproc.CODEDIR), 'runscript', 'func_from_bids.py')
                        cmd = [
                            script,
                            '--input', bids_func_file,
                            '--output', dest_nii,
                            '--sec-base', sec_base,
                            '--skip', task['SKIP'],
                            '--num-vol', task['NUMVOL'],
                            '--work-dir', work_dirname,
                            '--num-echos', numechos
                        ]
                        logfile_base = self._io_file_fmt(cmd)
                        job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))

                
        self.scans.reset_default_sessionid()
        return job_spec_list

    def fmap_from_bids(self, overwrite=True):
        job_spec_list = list()
        self.reset_steplog()
        sub = self.conf.iproc.SUB
        preptool = self.conf.fmap.preptool
        b02b0_fname = os.path.join(self.conf.iproc.CODEDIR, 'configs/b02b0.cnf')
        for sessionid,sess in self.scans.sessions():
            ses = sessionid
            for fmap_dir,fmap_scans in self.scans.fieldmaps():
                fmap1_run = fmap_scans['FIRST_FMAP']
                fmap1_no_pad = f'{int(fmap1_run):03d}'
                fmap_dirname = f'{fmap_dir}_{fmap1_no_pad}'
                fmap_full_dirname = os.path.join(self.conf.iproc.NATDIR,sessionid,fmap_dirname)
                dest_fieldmap_nii = f'{fmap_full_dirname}/{sessionid}_{fmap1_no_pad}_fieldmap' #removing .nii.gz affix to also make masked version for QC 2025.06.11 JS

                ## added from LD for bids integration on 2025.03.05
                outfiles = [f'{dest_fieldmap_nii}.nii.gz']
                mask_copy_nii = f'{fmap_full_dirname}/{sessionid}_{fmap1_no_pad}_mag_img_brain_mask.nii.gz'

                if self._outfiles_skip(overwrite,outfiles):
                    continue

                # find the files we need in BIDS directory
                if preptool == 'topup':
                    input1_bids_fname = fmap_scans['FIRST_BIDS_FNAME']
                    input2_bids_fname = fmap_scans['SECOND_BIDS_FNAME']
                    #input1_json_fname = input1_bids_fname.rstrip('.nii.gz') + '.json' #rstrip will keep on stripping so NOPE
                    #input2_json_fname = input2_bids_fname.rstrip('.nii.gz') + '.json'
                    input1_json_fname = re.sub(r'.nii.gz','.json',input1_bids_fname)
                    input2_json_fname = re.sub(r'.nii.gz','.json',input2_bids_fname)

                    # final output directory and filenames
                    dest_fmap1_nii = os.path.join(fmap_full_dirname, 'fmap1_img.nii.gz')
                    dest_fmap2_nii = os.path.join(fmap_full_dirname, 'fmap2_img.nii.gz')

                    ## 2025.03.05: added from LD for bids integration 
                    input1_series_number = commons.get_json_entity(input1_json_fname, 'SeriesNumber')
                    input2_series_number = commons.get_json_entity(input2_json_fname, 'SeriesNumber')
                    ## 

                    totalReadoutTime1 = commons.get_json_entity(input1_json_fname,'TotalReadoutTime')
                    totalReadoutTime2 = totalReadoutTime1 #commons.get_json_entity(input1_json_fname)
                    if totalReadoutTime1 != totalReadoutTime2:
                        raise ValueError(f'{totalReadoutTime1} != {totalReadoutTime2}. TotalReadoutTime from {input1_json_fname} does not match {input2_json_fname}')
                    
                    script = os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'fmap_from_bids_topup.sh')
                    cmd = [ script,
                            input1_bids_fname,
                            input2_bids_fname,
                            fmap_full_dirname,
                            self.conf.iproc.CODEDIR,
                            str(totalReadoutTime2),
                            dest_fieldmap_nii,
                            self.conf.iproc.OUTDIR,
                            mask_copy_nii ] # 2025.03.05: added OUTDIR, mask_copy_nii from LD for bids integration
                
                elif preptool == 'fsl_prepare_fieldmap':
                    print('----FSL PREPARE FIELDMAP----')
                    script = os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'fmap_from_bids.py')
                    print(f'----{script}----')
                    dest_fmapm_nii = os.path.join(fmap_full_dirname, 'mag_img.nii.gz')
                    dest_fmapp_nii = os.path.join(fmap_full_dirname, 'pha_img.nii.gz')
                    bids_fmapp_file = fmap_scans['SECOND_BIDS_FNAME']
                    bids_fmapm_files = fmap_scans['FIRST_BIDS_FNAME']
                    # Ensure these are always lists (single files come back as strings)
                    if isinstance(bids_fmapm_files, str):
                        bids_fmapm_files = [bids_fmapm_files]
                    if isinstance(bids_fmapp_file, str):
                        bids_fmapp_file = [bids_fmapp_file]
                    cmd = [script]
                    cmd.append('--input-fmapm')
                    cmd.extend(bids_fmapm_files)
                    cmd.append('--input-fmapp')
                    cmd.extend(bids_fmapp_file)
                    cmd.extend([
                        '--output-fmapm', dest_fmapm_nii,
                        '--output-fmapp', dest_fmapp_nii,
                        '--output-fieldmap', f'{dest_fieldmap_nii}.nii.gz',
                        '--work-dir', os.path.join(self.conf.iproc.WORKDIR, f'FMAP_{ses}'),
                        '--output-maskcopy', mask_copy_nii
                    ])
                    ## 2025.03.05: output-maskcopy added from Lauren for bids integration
                    logger.info(f'fmapp file is {bids_fmapp_file}')
                else:
                    raise Exception(f'unknown preptool {preptool}')
                # create output directory
                if not os.path.exists(fmap_full_dirname):
                    os.makedirs(fmap_full_dirname)

                logger.info(sp.list2cmdline(cmd))
                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd,logfile_base, outfiles))

        self.scans.reset_default_sessionid()
        return job_spec_list

    def xnat_to_nii_gz_anat(self, overwrite=True):
        stepname_base = 'xnat_to_nii_gz_anat'
        logger.debug(stepname_base)

        job_spec_list = []
        self.reset_steplog()
        for sessionid,sess in self.scans.anat_sessions():
            for anat_subdir,anat_scan in self.scans.anats():
                ANAT_SCAN_NO = int(anat_scan['ANAT'])
                anat_no_padded = f'{ANAT_SCAN_NO:03d}'
                anat_dirname = f'{anat_subdir}_{anat_no_padded}'
                anat_dir = os.path.join(self.conf.iproc.NATDIR, sessionid, anat_dirname)
                t2_scan_no = int(anat_scan['T2'])
                t2_session_id = anat_scan['T2_SESSION_ID']
                is_t2 = t2_scan_no and t2_session_id == '0'
                anat_name = sessionid + '_mpr' + anat_no_padded
                if is_t2:
                    anat_name = sessionid + '_t2w' + anat_no_padded
                logger.debug(f'name for {ANAT_SCAN_NO} is {anat_name}')
                work_name = anat_dirname + '_' + sessionid
                workdir_anat = os.path.join(self.conf.iproc.WORKDIR, work_name) ## why workdir? Shouldn't this be outdir?
                outnii = os.path.join(anat_dir,anat_name + '.nii.gz')
                outnii_reorient = os.path.join(anat_dir,anat_name + '_reorient.nii.gz')
                outfiles = [outnii_reorient]
                if self._outfiles_skip(overwrite, outfiles):
                    continue

                logger.debug(f'making {anat_dir}')
                if not os.path.exists(anat_dir):
                    os.makedirs(anat_dir)

                codedir = os.path.expanduser(self.conf.iproc.CODEDIR)
                cmd = [os.path.join(codedir, 'runscript', 'xnat_to_nii_gz_anat.sh'),
                    workdir_anat,
                    sessionid,
                    str(ANAT_SCAN_NO),
                    self.conf.iproc.CODEDIR,
                    self.conf.xnat.XNAT_ALIAS,
                    self.conf.xnat.XNAT_PROJECT,
                    outnii,
                    outnii_reorient,
                    self.conf.iproc.QDIR
                    ]
                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd, logfile_base, outfiles))
        self.scans.reset_default_sessionid()
        return job_spec_list

    def recon_all(self, overwrite=True):
        logger.debug('fs_recon_all')
        job_spec_list = []
        self.reset_steplog()
        for sessionid,sess in self.scans.anat_sessions():
            for anat_subdir, anat_scan in self.scans.anats():
                # Zero-pad ANAT scan number
                anatno = f'{int(self.scans.scan_no):03d}'
                fs_sub = f'{sessionid}_{anatno}'
                anat_dirname = f'{anat_subdir}_{anatno}'
                anat_vol = os.path.join(self.conf.fs.SUBJECTS_DIR,fs_sub, 'mri', 'T1.mgz')
                pial_surf = os.path.join(self.conf.fs.SUBJECTS_DIR,fs_sub, 'surf', 'lh.pial')
                t2_scan_no = int(anat_scan['T2'])
                t2_scan_no_padded = f'{t2_scan_no:03d}'
                t2_session_id = anat_scan['T2_SESSION_ID']
                is_t2 = t2_scan_no and t2_session_id == '0'
                has_t2 = t2_scan_no and (t2_session_id and t2_session_id != '0')
                if is_t2:
                    # do not run recon-all on a T2w scan
                    continue
                t2_reorient = '__none__'
                if has_t2:
                    fname = f'{t2_session_id}_t2w{t2_scan_no_padded}_reorient.nii.gz'
                    expr = os.path.join(
                        self.conf.iproc.NATDIR,
                        t2_session_id,
                        '*',
                        fname
                    )
                    logger.info(f'searching for reoriented T2w with glob {expr}')
                    files = glob.glob(expr)
                    if not len(files):
                        raise Exception(f'could not find reoriented T2w with glob {expr}')
                    if len(files) > 1:
                        raise Exception(f'found too many reoriented T2w files {files}')
                    t2_reorient = files[0]
                    logger.info(f'found reoriented T2w {t2_reorient}')

                mpr_reorient = os.path.join(
                    self.conf.iproc.NATDIR,
                    sessionid,
                    anat_dirname,
                    f'{sessionid}_mpr{anatno}_reorient.nii.gz'
                )
                outfiles = [anat_vol,pial_surf]
                if self._outfiles_skip(overwrite,outfiles):
                    continue

                cmd = [
                    os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'recon_all.sh'),
                    self.conf.iproc.SUB,
                    fs_sub,
                    mpr_reorient,
                    t2_reorient,
                    self.conf.fs.SUBJECTS_DIR,
                    self.conf.out_atlas.FS6,
                    self.conf.iproc.SCRATCHDIR,
                    self.conf.iproc.CODEDIR
                ]
                logger.debug(json.dumps(cmd, indent=2))

                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))
        self.scans.reset_default_sessionid()
        return job_spec_list

    def xnat_to_nii_gz_task(self, overwrite=True):
        logger.debug('xnat_to_nii_gz_task')

        job_spec_list = []
        self.reset_steplog()
        # scans.sessions() and scans.tasks() are special iterators that will
        # update the state of the scan object,
        # for use by _io_file_fmt or other functions.
        # This ay the scans object always has a readily-accessible description
        #of the scan it is currently operating on.
        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                task_scan_no = bold_scan['BLD']
                task = self.scans.task_dict[task_type]
                NUMECHOS = task['NUMECHOS']
                bold_no = f'{int(task_scan_no):03d}'

                task_dirname  = f'{task_type}_{bold_no}'
                file_dir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)

                ### JENN: REMOVING EXTENTION SO WE CAN ADD ECHO APPEND
                file_name = sessionid + '_bld' + bold_no + '_reorient_skip'
                outnii=os.path.join(file_dir, file_name)
                outfiles = [outnii]
                outfiles_ext = [x + '.nii.gz' for x in outfiles]

                if not (int(NUMECHOS) == 1): #MULTIECHO
                    file_name = sessionid + '_bld' + bold_no + '_reorient_skip'
                    outnii=os.path.join(file_dir, file_name)
                    outfiles_echo = [outnii]
                    if self._outfiles_skip(overwrite, outfiles_ext):
                        continue
                else: #SINGLE ECHO
                    if self._outfiles_skip(overwrite, outfiles_ext):
                        continue

                work_name = task_dirname + "_" + sessionid
                workdir = os.path.join(self.conf.iproc.WORKDIR, work_name)
                task = self.scans.task_dict[task_type]
                SKIP = task['SKIP']
                NUMVOL = task['NUMVOL']
                
                
                if not os.path.exists(workdir):
                    os.makedirs(workdir)

                if not os.path.exists(file_dir):
                    os.makedirs(file_dir)

                cmd=[os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'xnat_to_nii_gz_task.sh'),
                        workdir,
                        sessionid,
                        str(task_scan_no),
                        self.conf.iproc.CODEDIR,
                        self.conf.xnat.XNAT_ALIAS,
                        self.conf.xnat.XNAT_PROJECT,
                        outnii,
                        SKIP,
                        NUMVOL,
                        NUMECHOS,
                        self.conf.iproc.QDIR]

                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))
        self.scans.reset_default_sessionid()

        return job_spec_list

    def xnat_to_nii_gz_fieldmap(self, overwrite=True):
        '''prepares fieldmap dicoms for use in fm_unw.sh. Can handle both double echo and reverse plane encode fieldmaps'''
        job_spec_list = []
        self.reset_steplog()
        preptool = self.conf.fmap.preptool
        if preptool == 'topup':
            script = os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'xnat_to_nii_gz_fm_topup.sh')
        elif preptool == 'fsl_prepare_fieldmap':
            script = os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'xnat_to_nii_gz_fm.sh')
        else:
            raise Exception(f'unknown preptool {preptool}')
        for sessionid,sess in self.scans.sessions():
            for fmap_dir,fmap_scans in self.scans.fieldmaps():
                fmap1_no = int(fmap_scans['FIRST_FMAP'])
                fmap2_no = int(fmap_scans['SECOND_FMAP'])
                fmap1_no_pad = f'{fmap1_no:03d}'
                fmap_dirname = f'{fmap_dir}_{fmap1_no_pad}'
                file_dir = os.path.join(self.conf.iproc.NATDIR, sessionid, fmap_dirname)
                # phase scan is usually right after FMAP_MAG(m for magnitude).
                # this is the second, smaller set of field map dicoms in xnat
                # Phase scan has half the number of slices as Mag.
                logger.debug(json.dumps(fmap_scans, indent=2))
                if fmap1_no == 0 or fmap2_no == 0:
                    raise ValueError(f'something went wrong with fieldmap type assignment. \n {fmap1_no},{fmap2_no} \n {fmap_scans}')
                outfile = f'{file_dir}/{sessionid}_{fmap1_no_pad}_fieldmap' #removing .nii.gz affix to also make masked version for QC 2025.06.11 JS
                outfiles = [f'{outfile}.nii.gz']
                ## added from LD for bids integration on 2025.03.05
                mask_copy_nii = f'{file_dir}/{sessionid}_{fmap1_no_pad}_mag_img_brain_mask.nii.gz'
                ##

                if self._outfiles_skip(overwrite, outfiles):
                    continue
                #Create Output Directory
                if not os.path.exists(file_dir):
                    os.makedirs(file_dir)
                
                cmd = [
                    #os.path.join(self.conf.iproc.CODEDIR,'modwrap.sh'), 
                    #'module load fsl/4.0.3-ncf', 
                    #'module load fsl/5.0.4-ncf',
                    script,
                    sessionid,
                    str(fmap1_no),
                    str(fmap2_no),
                    file_dir,
                    self.conf.iproc.CODEDIR,
                    self.conf.xnat.XNAT_ALIAS,
                    self.conf.xnat.XNAT_PROJECT,
                    outfile,
                    self.conf.iproc.QDIR,
                    self.conf.iproc.OUTDIR, # 2025.03.05: added for fmap_topup_prep input by Lauren to match above
                    mask_copy_nii  # 2025.03.05: added by Lauren for QC FMAP PDF
                ]
                print(json.dumps(cmd, indent=2))

                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd, logfile_base, outfiles))
        self.scans.reset_default_sessionid()
        return job_spec_list

    def sesst_prep(self, overwrite=True):
        logger.debug('sesst_prep')
        job_spec_list = []
        self.reset_steplog()
        mpr_reorient = os.path.join(self.conf.template.TEMPLATE_DIR, f'{self.conf.T1.T1_SESS}_mpr_reorient.nii.gz')
        sub_dir = os.path.join(self.conf.fs.SUBJECTS_DIR, f'{self.conf.T1.T1_SESS}_{self.conf.T1.T1_SCAN_NO}')
        outfiles = [mpr_reorient]
        if self._outfiles_skip(overwrite, outfiles):
            return [] 
        
        run_cmd = [os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'sesst_prep.sh'),
            sub_dir,
            self.conf.T1.T1_SESS,
            self.conf.template.TEMPLATE_DIR,
            mpr_reorient]
        
        if not self.conf.T1.T1_SESS:
            raise Exception('no T1.T1_SESS in conf file')

        self.scans.set_anat(self.conf.T1.T1_SESS, self.conf.T1.T1_SCAN_NO)
        logfile_base = self._io_file_fmt(run_cmd)
        job_spec_list = [JobSpec(run_cmd, logfile_base, outfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list
       
    def fslroi_reorient_skip(self, overwrite=True):

        multiecho = 0

        logger.debug('fslroi_reorient_skip') 
                           
        self.reset_steplog()
        outfile_fname = f'{self.conf.iproc.SUB}_D01_{self.conf.template.MIDVOL_BOLDNAME}_bld{self.conf.template.MIDVOL_BOLDNO}_midvol.nii.gz'
        fslroi_outfile = os.path.join(self.conf.template.TEMPLATE_DIR, outfile_fname)

        numvol=self.scans.task_dict[self.conf.template.MIDVOL_BOLDNAME]['NUMVOL']  

        if int(self.conf.template.MIDVOL_VOLNO) > int(numvol):
            raise ValueError(f'MIDVOL_VOLNO {self.conf.template.MIDVOL_VOLNO} is greater than number of post-skip volumes {numvol}')
                
        outfiles = [fslroi_outfile]
        if self._outfiles_skip(overwrite, outfiles):
            return []

        self._set_rmfiles('fm_unwarp_and_mc_to_midvol', outfile_fname) 

        bold_no = int(self.conf.template.MIDVOL_BOLDNO)
        bold_no_pad = f'{bold_no:03d}'
        bold_dirname = f'{self.conf.template.MIDVOL_BOLDNAME}_{bold_no_pad}'
        fslroi_infile = os.path.join(
            self.conf.iproc.NATDIR,
            self.conf.template.MIDVOL_SESS,
            bold_dirname,
            self.conf.template.MIDVOL_SESS + '_bld' + self.conf.template.MIDVOL_BOLDNO + '_reorient_skip.nii.gz'
            )
        if not os.path.isfile(fslroi_infile):
            fslroi_infile = os.path.join(
                self.conf.iproc.NATDIR,
                self.conf.template.MIDVOL_SESS,
                bold_dirname,
                self.conf.template.MIDVOL_SESS + '_bld' + self.conf.template.MIDVOL_BOLDNO + '_reorient_skip_e1.nii.gz'
            )

            multiecho = 1
        
        if multiecho:
            run_cmd=[os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'fslroi_reorient_skip_ME.sh'),
                fslroi_infile, 
                fslroi_outfile,
                self.conf.template.MIDVOL_VOLNO,
                '1']
        else:
            run_cmd=[os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'fslroi_reorient_skip.sh'),
                fslroi_infile, 
                fslroi_outfile,
                self.conf.template.MIDVOL_VOLNO,
                '1']

        try:
            self.scans.set_midvol(self.conf)
        except KeyError as e:   
            logger.error('remember to set variables in [template] section of config!')
            raise e
        logfile_base = self._io_file_fmt(run_cmd)
        job_spec_list = [JobSpec(run_cmd, logfile_base, outfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list
    
    def fm_unwarp_midvol(self, overwrite=True):
        stepname ='fm_unwarp_midvol'
        logger.debug(stepname)
        
        self.reset_steplog()

        midvol_sessid = self.conf.template.MIDVOL_SESS
        bold_name = self.conf.template.MIDVOL_BOLDNAME
        midvol_sess = self.scans.scan_by_session[midvol_sessid]
        stripped_midvol_num = int(self.conf.template.MIDVOL_BOLDNO)
        midvol_scan = midvol_sess.bold_scans[stripped_midvol_num]
        fm_tasktype = midvol_scan['FMAP_DIR']
        
        fm_bold_no = "%03d" % int(midvol_scan['FIRST_FMAP'])
        fm_dirname = f'{fm_tasktype}_{fm_bold_no}'
        fdir = os.path.join(self.conf.iproc.NATDIR,midvol_sessid,fm_dirname)

        img = os.path.join(self.conf.template.TEMPLATE_DIR,f'{self.conf.iproc.SUB}_D01_{bold_name}_bld{self.conf.template.MIDVOL_BOLDNO}_midvol.nii.gz')
        dest_dir = os.path.dirname(img)
        warp_dir = dest_dir + f'/fm_unwarp{self.conf.template.MIDVOL_BOLDNO}'
        unwarped_img = os.path.join(self.conf.template.TEMPLATE_DIR,f'{self.conf.iproc.SUB}_D01_{bold_name}_midvol_unwarp.nii.gz')
        #unwarped_img = os.path.join(self.conf.template.TEMPLATE_DIR,f'{self.conf.iproc.SUB}_midvol_unwarp.nii.gz')
        # TODO: finish this, make naming align to conventions.
        outfiles = [unwarped_img]
        if self._outfiles_skip(overwrite,outfiles):
            return []

        fsl_unwarp_direction = self._unwarp_direction_from_sidecar(self.conf.template.TEMPLATE_DIR,midvol_sessid,self.conf.template.MIDVOL_BOLDNO)

        rmfiles = self._get_rmfiles(stepname)
        self._set_rmfiles('fm_unwarp_and_mc_to_midvol',unwarped_img) 

        # --- IS IT MULTIECHO?? ---
        dwellPath = os.path.join(self.conf.template.TEMPLATE_DIR,f'{midvol_sessid}_bld{self.conf.template.MIDVOL_BOLDNO}_dwellTime_e1.sec')
        print(dwellPath)

        if os.path.isfile(dwellPath):
            isME = '1'
        else:
            isME = '0'

        templateOut = os.path.join(self.conf.template.TEMPLATE_DIR,f'{self.conf.iproc.SUB}_midvol_unwarp.nii.gz')

        print(templateOut)

        run_cmd = [
            os.path.join(self.conf.iproc.CODEDIR, 'modwrap.sh'),
            'module load fsl/4.0.3-ncf',
            'module load fsl/5.0.4-ncf',
            os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'fm_unw.sh'),
            midvol_sessid,
            fdir,
            img,
            unwarped_img,
            fm_bold_no,
            dest_dir,
            warp_dir,
            fsl_unwarp_direction,
            isME

        ]

        print(run_cmd)
        self.scans.set_midvol(self.conf)
        logfile_base = self._io_file_fmt(run_cmd)

        if not self.args.no_remove_files:
            run_cmd.append(" ".join(rmfiles))

        job_spec_list = [JobSpec(run_cmd,logfile_base,outfiles,rmfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list
    
    def create_upsamped_midvol_target(self, overwrite=True):

        #NOW DOING 2mm target instead of 1.2mm

        stepname='create_upsamped_midvol_target'
        logger.debug(stepname) 
        
        self.reset_steplog()
        if self.conf.out_atlas.RESOLUTION == '111':
            resolution_str = '1p2i'
        else:
            resolution_str = '2mm'

        outfile = f'{self.conf.template.TEMPLATE_DIR}/{self.conf.iproc.SUB}_D01_{self.conf.template.MIDVOL_BOLDNAME}_midvol_unwarp_{resolution_str}.nii.gz'

        midvol_hdr = f'{self.conf.template.TEMPLATE_DIR}/{self.conf.iproc.SUB}_D01_{self.conf.template.MIDVOL_BOLDNAME}_midvol_hdr_tmp.nii.gz'

        

        outfiles = [outfile]
        if self._outfiles_skip(overwrite,outfiles):
            return []
    
        rmfiles = self._get_rmfiles(stepname)
        rmfiles.append(midvol_hdr)

        run_cmd = [os.path.join(self.conf.iproc.CODEDIR,'runscript','create_upsampled_midvol_target.sh'),
                    self.conf.iproc.SUB,
                    self.conf.template.MIDVOL_BOLDNAME,
                    self.conf.template.TEMPLATE_DIR,
                    resolution_str,
                    outfile]
    
        self.scans.set_midvol(self.conf)
        logfile_base = self._io_file_fmt(run_cmd)
        if not self.args.no_remove_files:
            run_cmd.append(" ".join(rmfiles))
        job_spec_list = [JobSpec(run_cmd,logfile_base,outfiles,rmfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list
    
    def fm_unwarp_and_mc_to_midvol(self, overwrite=True):
        # formerly p2
        # unwarps scans according to fieldmap specified in boldscan csv
        # aligns all timepoints to midvoltarg, product of create_upsamped_midvol_target
        # also performs motion correction relative to midvoltarg
        stepname = 'fm_unwarp_and_mc_to_midvol'
        logger.debug(stepname) 

        FD_LABEL = self.conf.template.FD_LABEL
        FD_THRESH = self.conf.template.FD_THRESH
         
        job_spec_list = []
        self.reset_steplog()
        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = "%03d" % int(scan_no)
                task_dirname  = f'{task_type}_{bold_no}'
                fm_bold_no = "%03d" % int(bold_scan['FIRST_FMAP'])
                numvol=self.scans.task_dict[task_type]['NUMVOL']
                
                fm_task_type = bold_scan['FMAP_DIR']
                fm_dirname = f'{fm_task_type}_{fm_bold_no}'

                fdir = os.path.join(self.conf.iproc.NATDIR,sessionid,fm_dirname)
                outputdir = os.path.join(self.conf.iproc.NATDIR,sessionid,task_dirname)

                numechos=self.scans.task_dict[task_type]['NUMECHOS']
                print('***** ECHOS: ' + numechos)

# ----- IF SINGLE ECHO, BUSINESS AS USUAL ----- 
                if int(numechos) == 1:

                    mc_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip.nii.gz')
                    mc_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc')
                    subjid = self.conf.iproc.SUB
                    if self.conf.out_atlas.RESOLUTION == '111':
                        target = os.path.join(self.conf.template.TEMPLATE_DIR,f'{subjid}_midvol_unwarp_1p2i')
                    else:
                        target = os.path.join(self.conf.template.TEMPLATE_DIR,f'{subjid}_midvol_unwarp_2mm')
                    flirt_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_midvol_to_midvoltarg.nii.gz')
                    flirt_mat_out = os.path.join(outputdir,f'{bold_no}_to_midvoltarg.mat')
                    scan_type=f'{sessionid}_bld{bold_no}'
                    midvol=os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_midvol')
                    regressors_mc_dat = os.path.join(outputdir,f'{scan_type}_regressors_mc.dat')
                    numvol_list = [str(x) for x in range(int(numvol))]
                    mc_out_matdir = mc_out+'.mat'
                    mc_mats = [os.path.join(mc_out_matdir, f'MAT_{n.zfill(4)}') for n in numvol_list]
                    affix_list = ['abs','abs_mean','rel','rel_mean']
                    mc_rms = [f'{mc_out}_{a}.rms' for a in affix_list]
                    outfiles = [flirt_out, flirt_mat_out, regressors_mc_dat]
                    outfiles.extend(mc_mats)
                    dest_dir = os.path.dirname(midvol)
                    warp_dir = dest_dir + f'/fm_unwarp{bold_no}'
                    EF_UD = os.path.join(warp_dir, 'EF_UD_warp.nii.gz')
                    outfiles.append(EF_UD)
                    if self._outfiles_skip(overwrite, outfiles):
                        continue
                    # if reorient_skip_mc.mat dir exists, delete, so we don't keep 
                    # creating endless reorient_skip_mc.mat+++++++ directories
                    if os.path.isdir(mc_out_matdir):   
                        shutil.rmtree(mc_out_matdir)
                        logger.debug('deleted:')
                        logger.debug(mc_out_matdir)
                    else:
                        logger.debug('not deleted because not found:')
                        logger.debug(mc_out_matdir)
        
                    if not os.path.exists(outputdir):
                        os.makedirs(outputdir)

                    fsl_unwarp_direction = self._unwarp_direction_from_sidecar(outputdir, sessionid, bold_no)

                    self._set_rmfiles('combine_warps_post_MNI', mc_mats)
                    rmfiles = self._get_rmfiles(stepname)
                    #add intermediates created by mcflirt to deletion list for this step
                    rmfiles.append(mc_out + '.nii.gz')
                    rmfiles += mc_rms

                    # note: p2.sh calls fm_unw.sh
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','fm_unwarp_and_mc_to_midvol.sh'),
                        mc_in,
                        mc_out,
                        target,
                        flirt_out,
                        flirt_mat_out,
                        scan_type,
                        numvol,
                        outputdir,
                        self.conf.iproc.CODEDIR,
                        sessionid,
                        fm_bold_no,
                        midvol,
                        fdir,
                        regressors_mc_dat,
                        dest_dir,
                        warp_dir,
                        fsl_unwarp_direction,
                        '0',
                        FD_THRESH,
                        FD_LABEL] #0 for single echo
           
                    logfile_base = self._io_file_fmt(cmd)
                    if not self.args.no_remove_files:
                        cmd.append(" ".join(rmfiles))
                    job_spec_list.append(JobSpec(cmd, logfile_base, outfiles, rmfiles))

# ----- IF ME, FIRST GET AFFINE REG FOR 1st ECHO ----- 
                
                else:
                    print(" ----- THIS IS A MULTI-ECHO BOLD VOLUME -----")
                    mc_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_e1.nii.gz')
                    mc_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_e1')
                    subjid = self.conf.iproc.SUB
                    #target = os.path.join(self.conf.template.TEMPLATE_DIR,"%s_midvol_unwarp_1p2i" % subjid)
                    #target = os.path.join(self.conf.template.TEMPLATE_DIR,f'{subjid}_midvol_unwarp')
                    #target = os.path.join(self.conf.template.TEMPLATE_DIR,f'{subjid}_midvol_unwarp_2mm')
                    if self.conf.out_atlas.RESOLUTION == '111':
                        target = os.path.join(self.conf.template.TEMPLATE_DIR,f'{subjid}_midvol_unwarp_1p2i')
                    else:
                        target = os.path.join(self.conf.template.TEMPLATE_DIR,f'{subjid}_midvol_unwarp_2mm')
                    
                    flirt_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_midvol_to_midvoltarg_e1.nii.gz')
                    flirt_mat_out = os.path.join(outputdir,f'{bold_no}_to_midvoltarg.mat')
                    scan_type=f'{sessionid}_bld{bold_no}'
                    midvol=os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_midvol')
                    regressors_mc_dat = os.path.join(outputdir,f'{scan_type}_regressors_mc.dat')
                    numvol_list = [str(x) for x in range(int(numvol))]
                    mc_out_matdir = mc_out+'.mat'
                    mc_mats = [os.path.join(mc_out_matdir, f'MAT_{n.zfill(4)}') for n in numvol_list]
                    affix_list = ['abs','abs_mean','rel','rel_mean']
                    mc_rms = [f'{mc_out}_{a}.rms' for a in affix_list]
                    outfiles = [flirt_out, flirt_mat_out, regressors_mc_dat]
                    outfiles.extend(mc_mats)
                    dest_dir = os.path.dirname(midvol)
                    warp_dir = dest_dir + f'/fm_unwarp{bold_no}'
                    EF_UD = os.path.join(warp_dir, 'EF_UD_warp.nii.gz')
                    outfiles.append(EF_UD)
                    if self._outfiles_skip(overwrite, outfiles):
                        continue
                    # if reorient_skip_mc.mat dir exists, delete, so we don't keep 
                    # creating endless reorient_skip_mc.mat+++++++ directories
                    if os.path.isdir(mc_out_matdir):   
                        shutil.rmtree(mc_out_matdir)
                        logger.debug('deleted:')
                        logger.debug(mc_out_matdir)
                    else:
                        logger.debug('not deleted because not found:')
                        logger.debug(mc_out_matdir)
        
                    if not os.path.exists(outputdir):
                        os.makedirs(outputdir)

                    fsl_unwarp_direction = self._unwarp_direction_from_sidecar(outputdir,sessionid,bold_no)

                    self._set_rmfiles('combine_warps_post_MNI',mc_mats)
                    rmfiles = self._get_rmfiles(stepname)
                    #add intermediates created by mcflirt to deletion list for this step
                    rmfiles.append(mc_out+'.nii.gz')
                    rmfiles += mc_rms

                    # note: p2.sh calls fm_unw.sh
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','fm_unwarp_and_mc_to_midvol.sh'),
                        mc_in,
                        mc_out,
                        target,
                        flirt_out,
                        flirt_mat_out,
                        scan_type,
                        numvol,
                        outputdir,
                        self.conf.iproc.CODEDIR,
                        sessionid,
                        fm_bold_no,
                        midvol,
                        fdir,
                        regressors_mc_dat,
                        dest_dir,
                        warp_dir,
                        fsl_unwarp_direction,
                        '1',
                        FD_THRESH,
                        FD_LABEL] #1 for multi-echo
           
                    logfile_base = self._io_file_fmt(cmd)
                    if not self.args.no_remove_files:
                        cmd.append(" ".join(rmfiles))
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles,rmfiles))



        self.scans.reset_default_sessionid()
        return job_spec_list
        
    
    def fslmerge_meantime(self,merged_vol,globfiles,reorient=False, overwrite=True):
        logger.debug('fslmerge_meantime') 
        #wrapper on fslmerge
        # this is used multiple times in various locations
        #so I'm not going to worry about rmfiles right now
        outfiles = [merged_vol]
        self.reset_steplog()
        if self._outfiles_skip(overwrite,outfiles):
            return []
        fslmerge_cmd = [os.path.join(self.conf.iproc.CODEDIR,'runscript','fslmerge_meantime.sh')]
        fslmerge_cmd.append(merged_vol)
        run_cmd = fslmerge_cmd+globfiles
    
        self.scans.set_name('Merge')
        logfile_base = self._io_file_fmt(run_cmd)
        job_spec_list = [JobSpec(run_cmd,logfile_base,outfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list
  
    def align_to_midvol_mean(self,overwrite=True):
        logger.debug('align_to_midvol_mean') 
        # alignment to the midvols_mean template. 
        #as in calc_mc_and_align_to_midvol, we are aligning the 
        #field-map unwarped, upsampled middle volumes of each run to a target-- 
        #the midvol_mean (formerly meanBOLD) target is produced by a 
        #fslmerge_meantime over midvols from all sessions after alignment to 
        #the midvol target.
        # formerly p3.
        job_spec_list = []
        self.reset_steplog()
        subjid=self.conf.iproc.SUB
        for sessionid,sess in self.scans.sessions():
    
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = f'{int(scan_no):03d}'
                task_dirname = f'{task_type}_{bold_no}'
                outputdir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                if not os.path.exists(outputdir):
                    os.makedirs(outputdir)
    
                target = self.conf.template.midvols_mean
                bet_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_midvol_unwarp')
    
                # was on_allscans
                flirt_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_on_midmean.nii.gz')
                flirt_mat_out = os.path.join(outputdir,f'{bold_no}_to_allscans.mat')
    
                outfiles = [flirt_out, flirt_mat_out]
                if self._outfiles_skip(overwrite,outfiles):
                    continue
    
                cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','align_to_midvol_mean.sh'),
                    bet_out,
                    target,
                    flirt_out,
                    flirt_mat_out]
                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))
        self.scans.reset_default_sessionid()
        return job_spec_list    
    
    def bbreg(self, overwrite=True):
        # this computes a registration from the midvols_mean to the sesst NAT T1.
        logger.debug('bbreg') 
        
        self.reset_steplog()
        # might want to change to reflect change in midvols_mean, which was 
        #{sub}_meanBOLD_allscans
        vreg = os.path.join(self.conf.template.TEMPLATE_DIR,f'{self.conf.iproc.SUB}_allscans_meanBOLD_to_T1')
        vreg_dat = f'{vreg}.dat'
        vreg_mat = f'{vreg}.mat'
        outfiles = [vreg_dat, vreg_mat]
        affix_list = ['log', 'param', 'mincost', 'sum']
        bbreg_cruft = [f'{vreg}.{a}' for a in affix_list]
        movimg = self.conf.template.midvols_mean
        if self._outfiles_skip(overwrite,outfiles):
            return([]) 
        
        rmfiles = self._get_rmfiles('bbreg')
        rmfiles+=bbreg_cruft

        run_cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','bbreg.sh'),
            self.conf.T1.T1_SESS,
            self.conf.template.TEMPLATE_DIR,
            movimg,
            vreg_dat,
            vreg_mat]
    
        self.scans.set_anat(self.conf.T1.T1_SESS,self.conf.T1.T1_SCAN_NO)
        logfile_base = self._io_file_fmt(run_cmd)
        if not self.args.no_remove_files:
            run_cmd.append(" ".join(rmfiles))
        job_spec_list = [JobSpec(run_cmd,logfile_base,outfiles,rmfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list

    
    # past this point we're working with output spaces
    def compute_T1_MNI_warp(self, overwrite=True):
        logger.debug('compute_T1_MNI_warp') 
        
        self.reset_steplog()
        # I know this looks like some kind of error but that's its name
        invwarp_out = f'{self.conf.template.TEMPLATE_DIR}/MNI_to_{self.conf.T1.T1_SESS}_mni_underlay.mat.nii.gz'
        outfiles = [invwarp_out]
        if self._outfiles_skip(overwrite,outfiles):
            return([])
        
        run_cmd=[
            os.path.join(self.conf.iproc.CODEDIR,'runscript','compute_T1_MNI_warp.sh'),
            self.conf.template.TEMPLATE_DIR,
            invwarp_out,
            self.conf.out_atlas.MNI_RESAMP,
            self.conf.out_atlas.MNI_RESAMP_BRAIN,
            self.conf.out_atlas.MNI_RESAMP_BRAINMASK,
            self.conf.T1.T1_SESS
        ]
    
        self.scans.set_anat(self.conf.T1.T1_SESS,self.conf.T1.T1_SCAN_NO)
        logfile_base = self._io_file_fmt(run_cmd)
        job_spec_list = [JobSpec(run_cmd,logfile_base,outfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list
    
    def reg_MNI_CSF_WM_to_T1(self, overwrite=True):
        logger.debug('reg_MNI_CSF_WM_to_T1') 
        
        self.reset_steplog()
        csf_out = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks/csf_mask_mpr_reorient.nii.gz')
        wm_out = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks/wm_mask_mpr_reorient.nii.gz')
        outfiles = [csf_out,wm_out]
        if self._outfiles_skip(overwrite,outfiles):
            return([])
        
        run_cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','reg_MNI_CSF_WM_to_T1.sh'),
            self.conf.template.TEMPLATE_DIR,
            self.conf.T1.T1_SESS,
            csf_out,
            wm_out,
            self.conf.iproc.MASKSDIR,
            self.conf.out_atlas.MNI_RESAMP]
    
        self.scans.set_anat(self.conf.T1.T1_SESS, self.conf.T1.T1_SCAN_NO)
        logfile_base = self._io_file_fmt(run_cmd)
        job_spec_list = [JobSpec(run_cmd, logfile_base, outfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list

    def reg_T1_to_BOLD(self, overwrite=True):
        logger.debug('reg_T1_to_BOLD') 
        
        self.reset_steplog()

        reg = os.path.join(self.conf.template.TEMPLATE_DIR, f'{self.conf.iproc.SUB}_allscans_meanBOLD_to_T1')
        reg_dat = f'{vreg}.dat'
        reg_mat = f'{vreg}.mat'

        refimg = self.conf.template.midvols_mean
        if self._outfiles_skip(overwrite, outfiles):
            return([]) 
        
        rmfiles = self._get_rmfiles('bbreg')

        run_cmd=[os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'reg_T1_to_BOLD.sh'),
            self.conf.T1.T1_SESS,
            self.conf.template.TEMPLATE_DIR,
            movimg,
            vreg_dat,
            vreg_mat]
    
        self.scans.set_anat(self.conf.T1.T1_SESS, self.conf.T1.T1_SCAN_NO)
        logfile_base = self._io_file_fmt(run_cmd)
        if not self.args.no_remove_files:
            run_cmd.append(" ".join(rmfiles))
        job_spec_list = [JobSpec(run_cmd, logfile_base, outfiles, rmfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list

    
    def size_brainmask(self, overwrite=True):
        logger.debug('size_brainmask') 
        
        self.reset_steplog()
        mni_underlay_dilated_bm_out = f'{self.conf.template.TEMPLATE_DIR}/anat_mni_underlay_brain_mask_dil10.nii.gz'
        mpr_bm_out = f'{self.conf.template.TEMPLATE_DIR}/mpr_reorient_brain_mask_dil10.nii.gz'
        outfiles = [mni_underlay_dilated_bm_out,mpr_bm_out]
        if self._outfiles_skip(overwrite, outfiles):
            return([]) 
    
        cmd=[os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'size_brainmask.sh'),
            self.conf.template.TEMPLATE_DIR,
            mni_underlay_dilated_bm_out]
    
        self.scans.set_anat(self.conf.T1.T1_SESS, self.conf.T1.T1_SCAN_NO)
        logfile_base = self._io_file_fmt(cmd)
        job_spec_list = [JobSpec(cmd, logfile_base, outfiles)]
        self.scans.reset_default_sessionid()
        return job_spec_list
    
    def combine_warps_parallel(self, anat_space, overwrite=True):
        # this combines and applies warps across all slices of the BOLD data,
        # moving it, one time point at a time, into an output volume space.
        # The individual-time-point volumes are not moved into the corresponding
        # out volume directory until the next step, as they are intermediates.
        logger.debug('combine_warps_parallel') 
    
        job_spec_list = []
        self.reset_steplog()
        # 4 scan sessions per subject in DN2
        subjid=self.conf.iproc.SUB
        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = "%03d" % int(scan_no)
                
                numvol=self.scans.task_dict[task_type]['NUMVOL']
                numechos=self.scans.task_dict[task_type]['NUMECHOS']
                
                if anat_space=='T1':
                    outfile_base = f'{anat_space}_TARG_FILE'
                elif anat_space=='MNI': 
                    outfile_base = f'{anat_space}_TARG_FILE'
                else:
                    raise NotImplementedError('anat_space parameter to combine_warps_parallel() must be T1 or MNI')

                if int(numechos) == 1:
                    print('***** SINGLE-ECHO steps.combine_warps_parallel*****')
                    pyscript = os.path.join(self.conf.iproc.CODEDIR,'iProc_p4_sbatch_combined.py')
                    task_dirname  = f'{task_type}_{bold_no}'
                    outputdir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                    
                    mat_dir = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc.mat')
                    volnums = [ str(n) for n in range(int(numvol)) ]
                    out_file_names = [ f'{outfile_base}_{n.zfill(4)}.nii.gz' for n in volnums ]
                    bld_dir = f'{bold_no}_{anat_space}'
                    outfiles = [ os.path.join(outputdir, bld_dir, f) for f in out_file_names ]
        
                    split_in = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip.nii.gz')
                    rmfiles = self._get_rmfiles('combine_warps_parallel')

                    cmd = [
                        os.path.join(self.conf.iproc.CODEDIR, 'runscript/combine_warps_parallel.sbatch'),
                        split_in,
                        pyscript,
                        mat_dir,
                        numvol,
                        outputdir,
                        subjid,
                        task_type,
                        sessionid,
                        bold_no,
                        self.conf.template.TEMPLATE_DIR,
                        anat_space,
                        self.conf.out_atlas.MNI_RESAMP,
                        self.conf.iproc.SCRATCHDIR
                    ]
    
                    logfile_base = self._io_file_fmt(cmd)

                    if not self.args.no_remove_files:
                        cmd.append(" ".join(rmfiles))
                    job_spec = JobSpec(cmd,logfile_base,outfiles,rmfiles)
        
                    # the presence of these files indicates that combine_warps_post and 
                    # combine_warps_post_MNI completed successfully
                    reo_outfile = os.path.join(
                        self.conf.iproc.NAT_RESAMP_DIR,
                        sessionid,
                        task_dirname,
                        f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat.nii.gz'
                    )
                    merge_outfile = os.path.join(
                        self.conf.iproc.MNI_RESAMP_DIR,
                        sessionid,
                        task_dirname,
                        f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni.nii.gz'
                    )
                    outfiles = [
                        reo_outfile,
                        merge_outfile
                    ]

                    logger.debug('checking for files to skip combine_warps_parallel')
                    logger.debug(json.dumps(outfiles, indent=2))
                    if self._outfiles_skip(overwrite, outfiles):
                        # this will allow the executor to avoid running the job, 
                        # while still having a dummy job object to pin dependent jobs to 
                        job_spec.skip = True

                    job_spec_list.append(job_spec)

                else: 
                    print('***** MULTI-ECHO steps.combine_warps_parallel*****')
                    pyscript = os.path.join(self.conf.iproc.CODEDIR,'iProc_p4_sbatch_combined_ME.py')
                    
                    volnums = [str(n) for n in range(int(numvol))]

                    for thisecho in range(1,int(numechos) + 1):
                        task_dirname  = f'{task_type}_{bold_no}'
                        outputdir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                        mat_dir = os.path.join(outputdir,f"{sessionid}_bld{bold_no}_reorient_skip_mc_e1.mat")

                        out_file_names = [ f'{outfile_base}_{n.zfill(4)}.nii.gz' for n in volnums ]
                        bld_dir = f'{bold_no}_{anat_space}_e{thisecho}'
                        outfiles = [ os.path.join(outputdir, bld_dir, f) for f in out_file_names ]
            
                        split_in = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip_e{str(thisecho)}.nii.gz')
                        rmfiles = self._get_rmfiles('combine_warps_parallel')

                        cmd = [
                            os.path.join(self.conf.iproc.CODEDIR, 'runscript/combine_warps_parallel_ME.sbatch'),
                            split_in,
                            pyscript,
                            mat_dir,
                            numvol,
                            outputdir,
                            subjid,
                            task_type,
                            sessionid,
                            bold_no,
                            self.conf.template.TEMPLATE_DIR,
                            anat_space,
                            self.conf.out_atlas.MNI_RESAMP,
                            self.conf.iproc.SCRATCHDIR,
                            str(thisecho)
                        ]
            
                        logfile_base = self._io_file_fmt(cmd)

                        if not self.args.no_remove_files:
                            cmd.append(" ".join(rmfiles))
                        job_spec = JobSpec(cmd,logfile_base,outfiles,rmfiles)
            
                        # the presence of these files indicates that combine_warps_post and 
                        # combine_warps_post_MNI completed successfully
                        reo_outfile = os.path.join(
                            self.conf.iproc.NAT_RESAMP_DIR,
                            sessionid,
                            task_dirname,
                            f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_e{thisecho}.nii.gz'
                        )
                        merge_outfile = os.path.join(
                            self.conf.iproc.MNI_RESAMP_DIR,
                            sessionid,
                            task_dirname,
                            f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_e{thisecho}.nii.gz'
                        )
                        outfiles = [
                            reo_outfile,
                            merge_outfile
                        ]

                        logger.debug('checking for files to skip combine_warps_parallel')
                        logger.debug(json.dumps(outfiles, indent=2))
                        if self._outfiles_skip(overwrite, outfiles):
                            # this will allow the executor to avoid running the job, 
                            # while still having a dummy job object to pin dependent jobs to 
                            job_spec.skip = True

                        job_spec_list.append(job_spec)

        self.scans.reset_default_sessionid()
        return job_spec_list    
    
    def combine_warps_post(self, overwrite=True):
        # this combines the individual-time-point volumes created by 
        #combine_warps_parallel, and places the resulting volume in the
        # output volume space directory for NAT222 or NAT111
        logger.debug('combine_warps_post') 

        job_spec_list = []

        self.reset_steplog()
        dilated_brainmask = os.path.join(self.conf.template.TEMPLATE_DIR,'mpr_reorient_brain_mask_dil10.nii.gz')
        if not os.path.exists(dilated_brainmask):
            logger.error(dilated_brainmask)
            logger.error('brainmask does not exist!')
            #TODO: more graceful way of exiting
            exit(1)
        subjid=self.conf.iproc.SUB


        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                rmfiles = self._get_rmfiles('combine_warps_post')
                scan_no = bold_scan['BLD']
                bold_no = "%03d" % int(scan_no)
                task_dirname  = f'{task_type}_{bold_no}'
                numvol=self.scans.task_dict[task_type]['NUMVOL']
                numechos=self.scans.task_dict[task_type]['NUMECHOS']

                if int(numechos) == 1:
                    print('***** SINGLE-ECHO steps.combine_warps_post*****')

                    outputdir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR, sessionid, task_dirname)
                    if not os.path.exists(outputdir):
                        os.makedirs(outputdir) 
                    indir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                    bld_dir = f'{bold_no}_T1'
                    targ_warp_files = os.path.join(indir,bld_dir, "T1_TARG_WARP_")
                    merge_in = os.path.join(indir,bld_dir,"T1_TARG_FILE_")
                    targfile_glob = merge_in + '*' 
                    targwarp_glob = targ_warp_files + '*'
                    rmfiles += [targwarp_glob,targfile_glob]

                        
                    merge_out = os.path.join(outputdir,f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_tmp.nii.gz")
                    rmfiles.append(merge_out)
                    reorient_out = os.path.join(outputdir,f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat.nii.gz")
                    dilmask = os.path.join(self.conf.template.TEMPLATE_DIR,"mpr_reorient_brain_mask_dil10.nii.gz")
                    mean_out = os.path.join(outputdir, f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mean.nii.gz")
                    # do not delete mean_out -- needed for QC
                    midvol_num = str(int(numvol)//2)
                    midvol_pad = midvol_num.zfill(3)
                    midvol_out = os.path.join(outputdir, f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_vol{midvol_pad}.nii.gz")
                    outfiles = [
                        midvol_out,
                        reorient_out,
                        mean_out
                    ]
                    cmd = [
                        os.path.join(self.conf.iproc.CODEDIR, 'runscript/combine_warps_post.sh'),
                        merge_in,
                        merge_out,
                        numvol,
                        reorient_out,
                        dilmask,
                        mean_out,
                        midvol_out
                    ]

                    logfile_base = self._io_file_fmt(cmd)

                    if not self.args.no_remove_files:
                        cmd.append(" ".join(rmfiles))
                    job_spec = JobSpec(cmd,logfile_base,outfiles,rmfiles)

                    logger.debug('checking for files to skip combine_warps_post')
                    logger.debug(json.dumps(outfiles, indent=2))
                    if self._outfiles_skip(overwrite,outfiles):
                        # this will allow the executor to avoid running the job, 
                        # while still having a dummy job object to pin dependent jobs to 
                        job_spec.skip = True

                    job_spec_list.append(job_spec)

                else:
                    print('***** MULTI-ECHO steps.combine_warps_post*****')

                    for thisecho in range(1,int(numechos) + 1):
                        outputdir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR, sessionid, task_dirname)
                        if not os.path.exists(outputdir):
                            os.makedirs(outputdir) 
                        indir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                        bld_dir = f'{bold_no}_T1_e{thisecho}'
                        targ_warp_files = os.path.join(indir,bld_dir, "T1_TARG_WARP_")
                        merge_in = os.path.join(indir,bld_dir,"T1_TARG_FILE_")
                        targfile_glob = merge_in + '*' 
                        targwarp_glob = targ_warp_files + '*'
                        rmfiles += [targwarp_glob,targfile_glob]

                            
                        merge_out = os.path.join(outputdir,f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_tmp_e{thisecho}.nii.gz") 
                        rmfiles.append(merge_out)
                        reorient_out = os.path.join(outputdir,f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_e{thisecho}.nii.gz")
                        dilmask = os.path.join(self.conf.template.TEMPLATE_DIR,f'mpr_reorient_brain_mask_dil10.nii.gz')
                        mean_out = os.path.join(outputdir, f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mean_e{thisecho}.nii.gz")
                        # do not delete mean_out -- needed for QC
                        midvol_num = str(int(numvol)//2)
                        midvol_pad = midvol_num.zfill(3)
                        midvol_out = os.path.join(outputdir, f"{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_vol{midvol_pad}_e{thisecho}.nii.gz")
                        outfiles = [
                            midvol_out,
                            reorient_out,
                            mean_out
                        ]
                        cmd = [
                            os.path.join(self.conf.iproc.CODEDIR, 'runscript/combine_warps_post.sh'),
                            merge_in,
                            merge_out,
                            numvol,
                            reorient_out,
                            dilmask,
                            mean_out,
                            midvol_out
                        ]

                        logfile_base = self._io_file_fmt(cmd)

                        if not self.args.no_remove_files:
                            cmd.append(" ".join(rmfiles))
                        job_spec = JobSpec(cmd,logfile_base,outfiles,rmfiles)

                        logger.debug('checking for files to skip combine_warps_post')
                        logger.debug(json.dumps(outfiles, indent=2))
                        if self._outfiles_skip(overwrite,outfiles):
                            # this will allow the executor to avoid running the job, 
                            # while still having a dummy job object to pin dependent jobs to 
                            job_spec.skip = True

                        job_spec_list.append(job_spec)
 
        self.scans.reset_default_sessionid()
        return job_spec_list    

    def combine_warps_post_MNI(self, overwrite=True):
        # this combines the individual-time-point volumes created by 
        #combine_warps_parallel, and places the resulting volume in the
        # output volume space directory for MNI222 or MNI111
        logger.debug('combine_warps_post_MNI') 
 
        job_spec_list = []
        self.reset_steplog()
        # 4 scan sessions per subject in DN2
        subjid=self.conf.iproc.SUB
        


        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                rmfiles = self._get_rmfiles('combine_warps_parallel_MNI')
                scan_no = bold_scan['BLD']
                bold_no = "%03d" % int(scan_no)
                task_dirname  = f'{task_type}_{bold_no}'
                numvol = self.scans.task_dict[task_type]['NUMVOL']
                numechos=self.scans.task_dict[task_type]['NUMECHOS']

                if int(numechos) == 1:
                    print('***** SINGLE-ECHO steps.combine_warps_post*****')

                    outputdir = os.path.join(self.conf.iproc.MNI_RESAMP_DIR, sessionid, task_dirname)
                    if not os.path.exists(outputdir):
                        os.makedirs(outputdir)
                    indir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                    bld_dir = f'{bold_no}_MNI'
                    merge_in = os.path.join(indir,bld_dir,"MNI_TARG_FILE_")
                    targ_warp_files = os.path.join(indir,bld_dir, "MNI_TARG_WARP_")
                    targfile_glob = merge_in + '*' 
                    targwarp_glob = targ_warp_files + '*'
                    rmfiles += [targwarp_glob,targfile_glob]
                    dilmask = os.path.join(self.conf.template.TEMPLATE_DIR,"anat_mni_underlay_brain_mask_dil10.nii.gz")
                    midvol_num = str(int(numvol)//2)
                    midvol_pad = midvol_num.zfill(3)
                    midvol_out = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_vol{midvol_pad}.nii.gz')
        
                    mean_out = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_mean.nii.gz')
                    merge_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni.nii.gz')
                    # we will not delete merge_out because it is the output
                    outfiles = [
                        midvol_out,
                        mean_out,
                        merge_out
                    ]
        
                    cmd = [
                        os.path.join(self.conf.iproc.CODEDIR, 'runscript/combine_warps_post_MNI.sh'),
                        merge_in,
                        merge_out,
                        numvol,
                        dilmask,
                        mean_out,
                        midvol_out
                    ]
        
                    logfile_base = self._io_file_fmt(cmd)

                    if not self.args.no_remove_files:
                        cmd.append(" ".join(rmfiles))
                    job_spec = JobSpec(cmd,logfile_base,outfiles,rmfiles)

                    logger.debug('checking for files to skip combine_warps_post_MNI')
                    logger.debug(json.dumps(outfiles, indent=2))
                    if self._outfiles_skip(overwrite,outfiles):
                        # this will allow the executor to avoid running the job, 
                        # while still having a dummy job object to pin dependent jobs to 
                        job_spec.skip = True

                    job_spec_list.append(job_spec)


                else:
                    print('***** MULTI-ECHO steps.combine_warps_post*****')

                    for thisecho in range(1,int(numechos) + 1):

                        outputdir = os.path.join(self.conf.iproc.MNI_RESAMP_DIR, sessionid, task_dirname)

                        if not os.path.exists(outputdir):
                            os.makedirs(outputdir)

                        indir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                        bld_dir = f'{bold_no}_MNI_e{thisecho}'
                        merge_in = os.path.join(indir,bld_dir,"MNI_TARG_FILE_")
                        targ_warp_files = os.path.join(indir,bld_dir, "MNI_TARG_WARP_")
                        targfile_glob = merge_in + '*' 
                        targwarp_glob = targ_warp_files + '*'
                        rmfiles += [targwarp_glob,targfile_glob]
                        dilmask = os.path.join(self.conf.template.TEMPLATE_DIR,f'anat_mni_underlay_brain_mask_dil10.nii.gz')
                        midvol_num = str(int(numvol)//2)
                        midvol_pad = midvol_num.zfill(3)
                        midvol_out = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_vol{midvol_pad}_e{thisecho}.nii.gz')
        
                        mean_out = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_mean_e{thisecho}.nii.gz')
                        merge_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_e{thisecho}.nii.gz')

                        # we will not delete merge_out because it is the output
                        outfiles = [
                            midvol_out,
                            mean_out,
                            merge_out
                        ]
            
                        cmd = [
                            os.path.join(self.conf.iproc.CODEDIR, 'runscript/combine_warps_post_MNI.sh'),
                            merge_in,
                            merge_out,
                            numvol,
                            dilmask,
                            mean_out,
                            midvol_out
                        ]
            
                        logfile_base = self._io_file_fmt(cmd)

                        if not self.args.no_remove_files:
                            cmd.append(" ".join(rmfiles))
                        job_spec = JobSpec(cmd,logfile_base,outfiles,rmfiles)

                        logger.debug('checking for files to skip combine_warps_post_MNI')
                        logger.debug(json.dumps(outfiles, indent=2))
                        if self._outfiles_skip(overwrite,outfiles):
                            # this will allow the executor to avoid running the job, 
                            # while still having a dummy job object to pin dependent jobs to 
                            job_spec.skip = True

                        job_spec_list.append(job_spec)


        self.scans.reset_default_sessionid()
        return job_spec_list    
    
    def calculate_nuisance_params(self,overwrite=True):
        logger.debug('calculate_nuisance_params') 
    
        self.reset_steplog()
        job_spec_list = []
        subjid=self.conf.iproc.SUB
        FD_LABEL = self.conf.template.FD_LABEL

        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = "%03d" % int(scan_no)
                task_dirname  = f'{task_type}_{bold_no}'
                numechos = self.scans.task_dict[task_type]['NUMECHOS']

                if int(numechos) == 1:
                    print('***** SINGLE-ECHO steps.calculate_nuisance_params*****')
                    codedir = os.path.expanduser(self.conf.iproc.CODEDIR)
                    outputdir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR,  sessionid, task_dirname)
                    natdir = os.path.join(self.conf.iproc.NATDIR,  sessionid, task_dirname)
                    resid_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat.nii.gz')
                    csf_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_csf_ts.dat')
                    csf_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','csf_mask_mpr_reorient.nii.gz')
                    wm_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_wm_ts.dat')
                    wm_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','wm_mask_mpr_reorient.nii.gz')
                    wb_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_wb_ts.dat')
                    wb_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','wb_mask_mpr_reorient.nii.gz')
                    phys_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_phys_ts.dat')
                    mc_ts = os.path.join(natdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc.par')
                    mcout_ts = os.path.join(natdir,f'{sessionid}_bld{bold_no}_reorient_skip_FD{FD_LABEL}_outlier_matrix.dat')
                    #mcout_ts = os.path.join(natdir,"%s_bld%s_reorient_skip_FD%s_outlier_matrix.dat" % (sessionid,bold_no, FD_LABEL))
                    nuis_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_nuis_ts.dat')
                    scang = f'{sessionid}_bld{bold_no}' 
                    nuis_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_nuis.dat')
                    nuis_out_nocensor = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_nuis_36P.dat')
                    outfiles = [nuis_out]
                    if self._outfiles_skip(overwrite,outfiles):
                        continue
        
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','calculate_nuisance_params.sh'),
                        resid_in,
                        csf_ts,
                        csf_mask,
                        wm_ts,
                        wm_mask,
                        wb_ts,
                        wb_mask,
                        phys_ts,
                        mc_ts,
                        nuis_ts,
                        scang,
                        nuis_out,
                        outputdir,
                        mcout_ts,
                        nuis_out_nocensor,
                        codedir]
        
                    logfile_base = self._io_file_fmt(cmd)
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))

                else:
                    print('***** MULTI-ECHO steps.calculate_nuisance_params*****')
                    codedir = os.path.expanduser(self.conf.iproc.CODEDIR)
                    outputdir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR, sessionid, task_dirname)
                    natdir = os.path.join(self.conf.iproc.NATDIR,  sessionid, task_dirname)
                    resid_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_e1.nii.gz')
                    csf_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_csf_ts.dat')
                    csf_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','csf_mask_mpr_reorient.nii.gz')
                    wm_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_wm_ts.dat')
                    wm_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','wm_mask_mpr_reorient.nii.gz')
                    wb_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_wb_ts.dat')
                    wb_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','wb_mask_mpr_reorient.nii.gz')
                    phys_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_phys_ts.dat')
                    mc_ts = os.path.join(natdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_e1.par') ##ECHO DIFF
                    mcout_ts = os.path.join(natdir,f'{sessionid}_bld{bold_no}_reorient_skip_e1_FD{FD_LABEL}_outlier_matrix.dat')
                    #mcout_ts = os.path.join(natdir,f'{sessionid}_bld{bold_no}_reorient_skip_e1_FD*_outlier_matrix.dat') ##ECHO DIFF
                    nuis_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_nuis_ts.dat')
                    scang = f'{sessionid}_bld{bold_no}' 
                    nuis_out = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_nuis.dat')
                    nuis_out_nocensor = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_nuis_36P.dat')
                    outfiles = [nuis_out]
                    if self._outfiles_skip(overwrite,outfiles):
                        continue
        
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','calculate_nuisance_params.sh'),
                        resid_in,
                        csf_ts,
                        csf_mask,
                        wm_ts,
                        wm_mask,
                        wb_ts,
                        wb_mask,
                        phys_ts,
                        mc_ts,
                        nuis_ts,
                        scang,
                        nuis_out,
                        outputdir,
                        mcout_ts,
                        nuis_out_nocensor,
                        codedir]
        
                    logfile_base = self._io_file_fmt(cmd)
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))
        self.scans.reset_default_sessionid()
        return job_spec_list 
    
    def calculate_wholebrain_only(self, overwrite=True):
        pass

    def nuisance_regress(self,anat_space, overwrite=True):
        
        #### -------- ONLY RUNNNG FOR SINGLE ECHO! ------- ####

        logger.debug('nuisance_regress') 
    
        self.reset_steplog()
        job_spec_list = []
        subjid=self.conf.iproc.SUB
        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = f'{int(scan_no):03d}'
                task_dirname  = f'{task_type}_{bold_no}'
                numechos = self.scans.task_dict[task_type]['NUMECHOS']

                if int(numechos) == 1:

                    nat_resamp_dir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR, sessionid, task_dirname)
                    nuis_out = os.path.join(nat_resamp_dir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_nuis.dat')
                    outputdir = None
                    if anat_space in ('MNI222','MNI111'): 
                        outputdir = os.path.join(self.conf.iproc.MNI_RESAMP_DIR, sessionid, task_dirname)
                        resid_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni.nii.gz')
                        resid_out = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_resid'
                        fullpath_resid_out = os.path.join(outputdir,resid_out)
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR,"anat_mni_underlay_brain_mask.nii.gz")
                        resid_outs = [f'{fullpath_resid_out}+tlrc.HEAD', f'{fullpath_resid_out}+tlrc.BRIK']
                    elif anat_space in ('NAT222','NAT111'): 
                        outputdir = nat_resamp_dir
                        resid_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat.nii.gz')
                        resid_out = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_resid'
                        fullpath_resid_out = os.path.join(outputdir,resid_out)
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mpr_reorient_brain_mask.nii.gz')
                        resid_outs = [f'{fullpath_resid_out}+orig.HEAD', f'{fullpath_resid_out}+orig.BRIK']

                    else:
                        raise NotImplementedError('anat_space parameter to nuisance_regress() must be T1 or MNI')
                    if not os.path.exists(outputdir):
                        os.makedirs(outputdir) 
                    outfiles = resid_outs + [nuis_out]
                    if self._outfiles_skip(overwrite,outfiles):
                        continue
        
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','nuisance_regress.sbatch'),
                        resid_in,
                        nuis_out,
                        resid_out,
                        outputdir,
                        mask,
                        self.conf.iproc.CODEDIR,
                        self.conf.iproc.SCRATCHDIR]
        
                    logfile_base = self._io_file_fmt(cmd)
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))

        self.scans.reset_default_sessionid()
        return job_spec_list 

    def wholebrain_only_regress(self,anat_space, overwrite=True):
        # this includes steps from nuisance variable calculation,
        #regression, and bandpassing, all in one step.
        # this is becasue we're only regressing out the whole-brain signal,
        #which is much simpler.

        #### -------- ONLY RUNNNG FOR SINGLE ECHO! ------- ####

        logger.debug('wholebrain_only_regress') 
    
        self.reset_steplog()
        job_spec_list = []
        subjid=self.conf.iproc.SUB
        FD_LABEL = self.conf.template.FD_LABEL
        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = f'{int(scan_no):03d}'
                task_dirname  = f'{task_type}_{bold_no}'
                numechos = self.scans.task_dict[task_type]['NUMECHOS']

                if int(numechos) == 1:

                    natdir = os.path.join(self.conf.iproc.NATDIR, sessionid, task_dirname)
                    nat_resamp_dir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR, sessionid, task_dirname)
                    #mcout_ts = os.path.join(natdir,f'{sessionid}_bld{bold_no}_reorient_skip_FD*_outlier_matrix.dat')
                    mcout_ts = os.path.join(natdir,f'{sessionid}_bld{bold_no}_reorient_skip_FD{FD_LABEL}_outlier_matrix.dat')

                    if anat_space in ('MNI222','MNI111'): 
                        outputdir = os.path.join(self.conf.iproc.MNI_RESAMP_DIR, sessionid, task_dirname)
                        resid_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni.nii.gz')
                        wb_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_wb_ts.dat')
                        wbmc_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_wb_ts_mcoutlier.dat')
                        wb_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','wm_mask_1mm.nii.gz')
                        resid_out = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_wb_resid'
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR,'anat_mni_underlay_brain_mask.nii.gz')
                    elif anat_space in ('NAT222','NAT111'): 
                        outputdir = nat_resamp_dir
                        resid_in = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat.nii.gz')
                        wb_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_mni_wb_ts.dat')
                        wbmc_ts = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_reorient_skip_wb_ts_mcoutlier.dat')
                        wb_mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mni_masks','wb_mask_mpr_reorient.nii.gz')
                        resid_out = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_wb_resid'
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR,'mpr_reorient_brain_mask.nii.gz')
                    else:
                        raise NotImplementedError('anat_space parameter to nuisance_regress() must be T1 or MNI')
     
                    fullpath_resid_out = os.path.join(outputdir,resid_out+'.nii.gz')
                    
                    outfiles = [fullpath_resid_out]
                    if self._outfiles_skip(overwrite,outfiles):
                        continue

                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','wholebrain_only_regress.sh'),
                        resid_in,
                        wb_ts,
                        wb_mask,
                        resid_out,
                        outputdir,
                        mask,
                        self.conf.iproc.CODEDIR,
                        self.conf.iproc.SCRATCHDIR,
                        mcout_ts,
                        wbmc_ts]
                       
                        
                    logfile_base = self._io_file_fmt(cmd)
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))

        self.scans.reset_default_sessionid()
        return job_spec_list 
     
    def bandpass(self,anat_space, overwrite=True):
        logger.debug('bandpass') 
    
        job_spec_list = []
        self.reset_steplog()
        subjid=self.conf.iproc.SUB
        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = "%03d" % int(scan_no)
                task_dirname  = f'{task_type}_{bold_no}'
                numechos=self.scans.task_dict[task_type]['NUMECHOS']

                if int(numechos) == 1:

                    print('***** SINGLE-ECHO steps.bandpass*****')
                    if anat_space in ('MNI222','MNI111'): 
                        outputdir = os.path.join(self.conf.iproc.MNI_RESAMP_DIR, sessionid, task_dirname)
                        resid_out = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_resid+tlrc')
                        bpss_out = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_mni_resid_bpss'
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR, 'anat_mni_underlay_brain_mask.nii.gz')
                    elif anat_space in ('NAT222','NAT111'): 
                        outputdir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR, sessionid, task_dirname)
                        resid_out = os.path.join(outputdir, f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_resid+orig')
                        bpss_out = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat_resid_bpss'
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR, 'mpr_reorient_brain_mask.nii.gz')
                    else:
                        raise NotImplementedError('anat_space parameter to bandpass() must be T1 or MNI')
                    fullpath_bpss_out_nii = os.path.join(outputdir, f'{bpss_out}.nii.gz')
                    logger.info(fullpath_bpss_out_nii)
                    outfiles = [fullpath_bpss_out_nii]
                    if self._outfiles_skip(overwrite,outfiles):
                        continue

                    rmfiles = [f'{resid_out}.{x}' for x in ['BRIK', 'HEAD']]

                    # unlike most other scripts here, this one will fail instead of overwrite existing files
                    # right now this is handled in runscript/bandpass.sbatch, but 
                    #this might be needed in future
                    #if os.path.exists(f):
                    #    os.remove(files)
        
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','bandpass.sbatch'),
                        resid_out,
                        bpss_out,
                        outputdir,
                        mask,
                        self.conf.iproc.CODEDIR,
                        self.conf.iproc.SCRATCHDIR]
        
                    logfile_base = self._io_file_fmt(cmd)
                    if not self.args.no_remove_files:
                        cmd.append(" ".join(rmfiles))
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles,rmfiles))

                else:

                    print('***** MULTI-ECHO steps.bandpass*****')
                    if anat_space in ('MNI222','MNI111'): 
                        outputdir = os.path.join(self.conf.iproc.MNI_RESAMP_DIR, sessionid, task_dirname)
                        resid_out = os.path.join(outputdir,'tedana',f'{sessionid}_bld{bold_no}_desc-denoised_bold.nii.gz')
                        resid_out_afni = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_mni_tedana_afni')
                        bpss_out = f'{sessionid}_bld{bold_no}_mni_tedana_bpss'
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR,"anat_mni_underlay_brain_mask.nii.gz")
                        space_affix = 'tlrc' ### e.g., Talairach view
                    elif anat_space in ('NAT222','NAT111'): 
                        outputdir = os.path.join(self.conf.iproc.NAT_RESAMP_DIR, sessionid, task_dirname)
                        resid_out = os.path.join(outputdir,'tedana',f'{sessionid}_bld{bold_no}_desc-denoised_bold.nii.gz')
                        resid_out_afni = os.path.join(outputdir,f'{sessionid}_bld{bold_no}_tedana_afni')
                        bpss_out = f'{sessionid}_bld{bold_no}_tedana_bpss'
                        mask = os.path.join(self.conf.template.TEMPLATE_DIR,"mpr_reorient_brain_mask.nii.gz")
                        space_affix = 'orig' ### e.g., T1 view
                    else:
                        raise NotImplementedError('anat_space parameter to bandpass() must be NAT111, NAT222, MNI111, or MNI222')
                    fullpath_bpss_out_nii = os.path.join(outputdir,f'{bpss_out}.nii.gz')
                    logger.info(fullpath_bpss_out_nii)
                    outfiles = [fullpath_bpss_out_nii]
                    if self._outfiles_skip(overwrite,outfiles):
                        continue

                    rmfiles = [f'{resid_out}.{f}' for f in ['BRIK', 'HEAD']]

                    # unlike most other scripts here, this one will fail instead of overwrite existing files
                    # right now this is handled in runscript/bandpass.sbatch, but 
                    #this might be needed in future
                    #if os.path.exists(f):
                    #    os.remove(files)
        
                    cmd=[os.path.join(self.conf.iproc.CODEDIR, 'runscript', 'bandpass_ME.sbatch'), #### need to convert resid_out to afni format (.BRIK, etc.) so bandpass_ME 
                        resid_out,
                        resid_out_afni,
                        space_affix,
                        bpss_out,
                        outputdir,
                        mask,
                        self.conf.iproc.CODEDIR,
                        self.conf.iproc.SCRATCHDIR]
        
                    logfile_base = self._io_file_fmt(cmd)
                    if not self.args.no_remove_files:
                        cmd.append(" ".join(rmfiles))
                    job_spec_list.append(JobSpec(cmd,logfile_base,outfiles,rmfiles))
        self.scans.reset_default_sessionid()
        return job_spec_list 
    
    def fs6_project_to_surface(self, overwrite=True):

        print('------- RUNNING MULTI-ECHO STEPS/FS6_PROJECT_TO_SURF -------')
        logger.debug('fs6_project_to_surface')

        # create fsaverage6 link if not present
        subjects_dir = Path(self.conf.fs.SUBJECTS_DIR)
        target = Path(self.conf.out_atlas.FS6)
        link = subjects_dir / 'fsaverage6'
        if not link.exists():
            logger.info(f'linking {target} to {link}')
            link.symlink_to(target)

        job_spec_list = []
        self.reset_steplog()

        sesst = self.conf.T1.T1_SESS
        subjid = self.conf.iproc.SUB
        for sessionid,sess in self.scans.sessions():
            for task_type,bold_scan in self.scans.tasks():
                scan_no = bold_scan['BLD']
                task = self.scans.task_dict[task_type]
                smooth = task['SMOOTHING']
                bold_no = "%03d" % int(scan_no)
                task_dirname  = f'{task_type}_{bold_no}'
                outputdir = os.path.join(
                    self.conf.iproc.FS6DIR,
                    sessionid,
                    task_dirname
                )
                boldpath = os.path.join(
                    self.conf.iproc.NAT_RESAMP_DIR,
                    sessionid,
                    task_dirname
                )
                if not os.path.exists(outputdir):
                    os.makedirs(outputdir) 
                
                surfdir = os.path.join(outputdir)

                numechos = self.scans.task_dict[task_type]['NUMECHOS']
                if int(numechos) == 1:
                    bold = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat'
                    bold2 = bold + '_resid_bpss'
                    bold3 = bold + '_wb_resid'
                    bold4 = bold + '_resid'
                    # this is one of the files in the last batch. Not a comprehensive list of files
                    outfiles = [os.path.join(surfdir,f'lh.{bold2}_fsaverage6_sm{smooth}.nii.gz')]

                    if self._outfiles_skip(overwrite,outfiles):
                        continue
        
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','fs6_project_to_surf.sh'),
                        bold,
                        bold2,
                        bold3,
                        sesst,
                        boldpath,
                        surfdir,
                        self.conf.iproc.SCRATCHDIR,
                        smooth,
                        bold4]
                else:
                    #bold = f'{sessionid}_bld{bold_no}_reorient_skip_mc_unwarp_anat'
                    bold_tedanaed = f'{sessionid}_bld{bold_no}_desc-denoised_bold'
                    bold_out = f'{sessionid}_bld{bold_no}_tedana'
                    bold_bpss = f'{bold_out}_bpss'
                    #resid_out = os.path.join(boldpath,'tedana',f'{sessionid}_bld{bold_no}_desc-denoised_bold.nii.gz')
                    #bold_out = bold + '_tedana'
                    # this is one of the files in the last batch. Not a comprehensive list of files
                    outfiles = [os.path.join(surfdir,f'lh.{bold_bpss}_fsaverage6_sm{smooth}.nii.gz')]

                    if self._outfiles_skip(overwrite,outfiles):
                        continue
    
                    cmd=[os.path.join(self.conf.iproc.CODEDIR,'runscript','fs6_project_to_surf_ME.sh'),
                        bold_tedanaed,
                        bold_out,
                        bold_bpss,
                        sesst,
                        boldpath,
                        surfdir,
                        self.conf.iproc.SCRATCHDIR,
                        smooth]
    
                logfile_base = self._io_file_fmt(cmd)
                job_spec_list.append(JobSpec(cmd,logfile_base,outfiles))

        self.scans.reset_default_sessionid()
        return job_spec_list


        
    ### 
    ## Helpers
    ###
    def load_rmfile_dump(self,stagename, initialize_blank=False):
        # try to load a crash file. if none exists, load finished file from previous step.
        # must be passed the name of the previous step.

        # first check if this is a rerun:
        if os.path.exists(self.rm_final_filename):
            with open(self.rm_final_filename, 'rb') as f:
                self.rmfiles=pickle.load(f)   
            logger.debug(f'Final rmfile found from a previous successful run of this step {self.rm_final_filename}')
            return
        if initialize_blank or self.args.blank_rmfiles:
            return
        try:
            assert(stagename)
            prior_final_dump_fname = os.path.join(self.conf.iproc.RMFILE_DUMP, f'{stagename}.final')
            with open(prior_final_dump_fname, 'rb') as f:
                self.rmfiles = pickle.load(f)
            logger.debug(f'final file {prior_final_dump_fname} loaded')
        except (OSError,IOError,AssertionError) as e:
            logger.debug(e)
            try:
                dump_fname = self.rm_dump_filename
                with open(dump_fname, 'rb') as f:
                    self.rmfiles=pickle.load(f)
            except (OSError,IOError) as e:
                logger.debug(e)
                logger.debug(dump_fname)
                logger.debug(prior_final_dump_fname)
                raise IOError('no appropriate dump file exists. Did you run the previous steps?')

    def _get_rmfiles(self, stepname):
        # this should work even in the case that the last two are "None"
        try: 
            rmfiles = self.rmfiles[stepname][self.scans.sessionid][self.scans.scan_no]
        except KeyError:
            rmfiles = []
        return rmfiles
        
    def _set_rmfiles(self, stepname, rmfiles):
        # this should work even in the case that the last two are "None"
        try:
            self.rmfiles[stepname][self.scans.sessionid][self.scans.scan_no] = rmfiles
        except KeyError:
            self.rmfiles[stepname]={}
            self.rmfiles[stepname][self.scans.sessionid] = {}
            self.rmfiles[stepname][self.scans.sessionid][self.scans.scan_no] = rmfiles
        # write to disk
        fname = self.rm_dump_filename
        with open(fname,'wb') as f:
            pickle.dump(self.rmfiles,f)
 
    @staticmethod
    def _unwarp_direction_from_sidecar(fdir, sessid, boldno):
        ''' returns unwarp direction for FSL, to be used in fm_unw.sh
                sessid: sessid
                boldno: boldno, zero padded to 3 digits, string format'''
        BIDS_sidecar = os.path.join(fdir, f'{sessid}_bld{boldno}.json')

        if not os.path.isfile(BIDS_sidecar):
            BIDS_sidecar = os.path.join(fdir, f'{sessid}_bld{boldno}_e1.json')
            if not os.path.isfile(BIDS_sidecar):
                BIDS_sidecar = os.path.join(fdir, f'{sessid}_bld{boldno}_reorient_skip_e1.json')

        BIDS_phase_direction = commons.get_json_entity(BIDS_sidecar,'PhaseEncodingDirection')
        if BIDS_phase_direction == 'j-':
            fsl_unwarpdirection = 'y-'
        elif BIDS_phase_direction == 'j':
            fsl_unwarpdirection = 'y'
        else:
            raise ValueError(f'unsupported phase encoding direction {BIDS_phase_direction}')
        return fsl_unwarpdirection

    def _io_file_fmt(self, run_cmd):
        # for scan_no, have this autodetect based on fieldmap/anat/bold flag and scan

        # get name of all runscripts, to get around fact that sometimes first element in list is a wrapper script
        runscripts = [s for s in run_cmd if '/runscript/' in str(s)]
        scriptnames = [os.path.basename(s) for s in runscripts]
        scriptname = '_'.join(scriptnames)
        sessionid = self.scans.sessionid if self.scans.sessionid else 'SESSID'
        scan_no = self.scans.scan_no if self.scans.scan_no else 'SCAN_NO' 
        scan_name = self.scans.scan_name if self.scans.scan_name else 'SCAN_NAME' 
        outfile_base = os.path.join(self.conf.iproc.LOGDIR,
                f'{self.conf.iproc.SUB}_{sessionid}_{scan_no}_{scan_name}_{scriptname}')
        return outfile_base
    
    def _outfiles_skip(self,overwrite,outfiles):

        outfiles_exist = {x:os.path.exists(x) for x in outfiles}
        existing_outfiles = [k for k,v in list(outfiles_exist.items()) if v]
        nonexisting_outfiles = [k for k,v in list(outfiles_exist.items()) if not v]
        
        if overwrite:
            return False 
        else:
            if not nonexisting_outfiles:
                logger.debug(f'outfiles exist {" ".join(existing_outfiles)}. Job will not be added to job list.')
                return True
            elif existing_outfiles: 
                logger.debug('outfiles are partially missing.')
                logger.debug(f'existing outfiles: {" ".join(existing_outfiles)}')
                logger.debug(f'missing outfiles: {" ".join(nonexisting_outfiles)}. Jobs will be added to job list for rerun.')
                return False
            else: # there are no existing outfiles
                logger.debug(f'outfiles do not exist {" ".join(nonexisting_outfiles)}. Jobs will be added to job list.')

                return False

