import re
import os
import glob
import logging
import json
import subprocess as sp
import collections as col
import iproc.commons as commons
logger = logging.getLogger(__name__)

def match_scan_no_to_bids(bids_base,scans):
    for sessionid,sess in scans.sessions():
        #set corresponding BIDS subdir
        bids_sessionid = sanitize(sessionid)
        bids_sessionid_dirname = f'ses-{bids_sessionid}'
        # take care of fmap
        # compile list of SeriesNumber:(task,run)
        bids_func_fullpath = os.path.join(bids_base,bids_sessionid_dirname,'func')
        bids_json_fglob = f'sub-{sess.subjid}_ses-{bids_sessionid}_*_bold.json'
        bids_json_glob = os.path.join(bids_func_fullpath,bids_json_fglob)
        scan_no_to_json = {}
        for json in glob.glob(bids_json_glob):
            # get series number from json, save in dict for later

            #try for single echo with direction:
            json_regex_dir = f'.*sub-{sess.subjid}_ses-{bids_sessionid}_task-(\w+)_dir-(\w+)_run-([0-9]+)_bold.json'
            bids_pair_tmp_dir = re.match(json_regex_dir,json)

            #try for single echo with direction:
            json_regex = f'.*sub-{sess.subjid}_ses-{bids_sessionid}_task-(\w+)_run-([0-9]+)_bold.json'
            bids_pair_tmp = re.match(json_regex,json)

            #try for single echo with direction:
            json_regex_dir_me = f'.*sub-{sess.subjid}_ses-{bids_sessionid}_task-(\w+)_dir-(\w+)_run-([0-9]+)_echo-([0-9]+)_bold.json'
            bids_pair_tmp_dir_me = re.match(json_regex_dir_me,json)

            #try for single echo with direction:
            json_regex_me = f'.*sub-{sess.subjid}_ses-{bids_sessionid}_task-(\w+)_run-([0-9]+)_echo-([0-9]+)_bold.json'
            bids_pair_tmp_me = re.match(json_regex_me,json)


            if bids_pair_tmp != None:
                bids_pair = bids_pair_tmp.groups()
                dirSpec = 0 # set to 0 if direction is NOT specified in file name
                ME = 0 # set to 0 if single echo
            elif bids_pair_tmp_dir != None:
                bids_pair = bids_pair_tmp_dir.groups()
                dirSpec = 1 #set to 1 if direction is specified in file name
                ME = 0 
            elif bids_pair_tmp_me != None:
                bids_pair = bids_pair_tmp_me.groups()
                dirSpec = 0 
                ME = 1 # set to 1 if multi-echo
            elif bids_pair_tmp_dir_me != None:
                bids_pair = bids_pair_tmp_dir_me.groups()
                dirSpec = 1
                ME = 1 
                
            series_no = get_json_entity(json,'SeriesNumber')
            scan_no_to_json[series_no]=bids_pair

        # Compile list of phase_SeriesNumber:BIDS_run_no
        bids_fmap_fullpath = os.path.join(bids_base,bids_sessionid_dirname,'fmap')
        bids_json_fglob = '*.json'.format(SUB=sess.subjid,SES=bids_sessionid)
        bids_json_glob = os.path.join(bids_fmap_fullpath,bids_json_fglob)

        fmap_jsons = glob.glob(bids_json_glob)
        if not fmap_jsons:
            logger.error(f'no JSON file found for {bids_json_glob}')
            raise IOError

        fmap_no_to_nifti = {}
        for json_fname in fmap_jsons:
            # get filenames by aquisition number
            series_no = get_json_entity(json_fname,'SeriesNumber')
                
            nifti_filename = re.sub(r'\.json$', '.nii.gz', json_fname)
            if not os.path.exists(nifti_filename):
                raise ValueError
            existing_fmap = fmap_no_to_nifti.get(series_no)
            logger.debug(f'{existing_fmap} {json_fname} {series_no}')
            if not existing_fmap:
                fmap_no_to_nifti[series_no] = nifti_filename 
            elif type(existing_fmap) == str:
                fmap_no_to_nifti[series_no] = [existing_fmap,nifti_filename]
            else:
                fmap_no_to_nifti[series_no].append(nifti_filename)

        # Compile list of anat_SeriesNumber:BIDS_run_no
        bids_anat_fullpath = os.path.join(bids_base,bids_sessionid_dirname,'anat')
        bids_T1_json_fglob = f'sub-{sess.subjid}_ses-{bids_sessionid}_*_T1w.json'
        bids_T2_json_fglob = f'sub-{sess.subjid}_ses-{bids_sessionid}_*_T2w.json'
        bids_T1_json_glob = os.path.join(bids_anat_fullpath,bids_T1_json_fglob)
        bids_T2_json_glob = os.path.join(bids_anat_fullpath,bids_T2_json_fglob)
        anat_no_to_json = {}
        anat_jsons = glob.glob(bids_T1_json_glob) + glob.glob(bids_T2_json_glob)
        if not anat_jsons and sess.anat_scans:
            logger.error(f'no JSON file found for {bids_T1_json_glob}')
            raise IOError
        for json in anat_jsons:
            # get series number for T1w anat from json, save in dict for later
            anat_regex = f'.*sub-{sess.subjid}_ses-{bids_sessionid}(?:_[^_]+)*_run-([0-9]+)_(T1w|T2w).json'
            anat_match = re.match(anat_regex,json)
            run_no = anat_match.group(1)
            series_no = get_json_entity(anat_match.string,'SeriesNumber')
            anat_no_to_json[series_no]=run_no
            print(anat_no_to_json)
            print(sess.anat_scans)
        try:
            for scan_no,anat_scan in iter(sess.anat_scans.items()):
                anat_scan['BIDS_ID'] = anat_no_to_json[scan_no]
        except KeyError as e:
            logger.debug('anat_no_to_json:')
            logger.debug(anat_no_to_json)
            logger.debug('anat_scan:')
            logger.debug(anat_scan)
            raise e

        ## Add this info into bold_scan objects
        for task_name,bold_scan in scans.tasks():
            scan_no = scans.scan_no 
            print(scan_no_to_json[scan_no])
            if (dirSpec == 1) and (ME == 0): # if topup and single echo
                try:
                    task,direction,run = scan_no_to_json[scan_no] 
                except Exception as e:
                    logger.debug(scan_no_to_json)    
                    raise e
                tname = f'{task.upper()}_{direction.upper()}_{run}'

            elif (dirSpec == 0) and (ME == 0):  #if fsl fieldmap and single echo
                try:
                    print(scan_no_to_json[scan_no])
                    task,run = scan_no_to_json[scan_no] 
                except Exception as e:
                    logger.debug(scan_no_to_json)    
                    raise e
                tname = f'{task.upper()}'

            elif (dirSpec == 1) and (ME == 1): # if topup and multi-echo
                try:
                    task,direction,run,echonum = scan_no_to_json[scan_no] 
                except Exception as e:
                    logger.debug(scan_no_to_json)    
                    raise e
                tname = f'{task.upper()}_{direction.upper()}_{run}'

            elif (dirSpec == 0) and (ME == 1): # if fsl fieldmap and multi-echo
                try:
                    task,run,echonum = scan_no_to_json[scan_no] 
                except Exception as e:
                    logger.debug(scan_no_to_json)    
                    raise e
                tname = f'{task.upper()}'

            if tname != task_name:
                errname=f'BIDS taskname "{task}" does not match boldscan task name "{task_name}" for sessid {sessionid}, scan {scan_no}'
                raise IOError(errname)
            bold_scan['BIDS_ID'] = run
            # correct naively-enumerated FMAP directories:
            fmap1_series_no = bold_scan['FIRST_FMAP']
            bold_scan['FMAP_DIR'] = 'FMAP'.format(fmap1_series_no)
            
        for fmap_dir,fmap_scan in scans.fieldmaps():
            
            
            fmap_scan['FIRST_BIDS_FNAME'] = load_fmap_file_to_scan(fmap_no_to_nifti,fmap_scan,'FIRST_FMAP')
            fmap_scan['SECOND_BIDS_FNAME'] = load_fmap_file_to_scan(fmap_no_to_nifti,fmap_scan,'SECOND_FMAP')

def load_fmap_file_to_scan(fmap_no_to_nifti,fmap_scan, scan_id):
    ''' 
    fmap_scan: fmap_scan from iproc/csvHandler
    scan_id: 'FIRST_FMAP' or 'SECOND_FMAP' 
    returns full path to fmap file, or list of such full paths
    '''

    fmap_series_no = fmap_scan[scan_id]
    logger.debug(fmap_scan)
    try:
        fmap_file = fmap_no_to_nifti[str(fmap_series_no)]

    except KeyError as e:
        logger.debug('fmap_no_to_nifti')
        logger.debug(fmap_no_to_nifti)
        raise e
    fmap_scan['DIR'] = f'FMAP'
    return fmap_file

def get_json_entity(json,entity):
    return str(commons.get_json_entity(json,entity))

class SplitTaskError(Exception):
    pass

def sanitize(s):
    regex = re.compile('[^a-zA-Z0-9]')
    return regex.sub('', s)

def split_task(s): 
    regex = re.compile('([a-zA-Z]+)_?(\d+)?') 
    match = regex.match(s) 
    if not match: 
        raise SplitTaskError(f'failed to split task "{s}"') 
    task,run = match.groups('1')
    return task,run
