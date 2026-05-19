import subprocess as sp
import os
import shutil
import logging
import time
import tempfile
import iproc.commons as commons

logger = logging.getLogger(__name__)
# probably going to want to create a page factory that produces pages with 
# certain hard-coded values, and others that can vary.
class page(object):
    # this object holds all the info you need to run a slicer command and 
    #produce a single page in a QC PDF.
    def __init__(self,infile,slicer):
        # to store the final outputs of a slicer command, 
        # tableaus are themselves aggregates of many pngs
        self.infile = infile
        self.tableau = None
        infile_basename = os.path.basename(self.infile)
        self.infile_basename = infile_basename.split('.')[0]
        # this is a dict with keys size,sample,width
        self.slicer = slicer

class qc_pdf_maker(object):
    #for holding internal settings
    def __init__(self, conf,plane):
        # pages are a list of page objects
        self.outdir = conf.iproc.QCDIR
        timestamp = time.time()
        self.scratch_home = os.path.join(self.outdir,'images')
        if not os.path.exists(self.scratch_home):
            os.makedirs(self.scratch_home)
        self.scratch = None
        self.pages = [] 
        self.conf = conf
        self.out_pdf = None #set by self.set_out_pdf
        self.scriptname = None #set by self.set_out_pdf
        self.script = None 
        self.plane = plane
        if plane == 'ax':
            # for use in fslswapdim. Order matters.
            self.swapdims=['-x','y','-z']
        elif plane == 'sag':
            self.swapdims=['y','z','-x']
        else:
            raise NotImplementedError
   
    def produce_pdf(self,name,save_intermediates=True,overwrite=True):
        self.scratch = tempfile.mkdtemp(dir=self.scratch_home)
        logfile_base = self._io_file_fmt()
        if not self.set_out_pdf_name(name,overwrite):
            job_spec = commons.JobSpec(None,logfile_base,[self.out_pdf])
            job_spec.skip = True
            return 
            
        # pdf name set. Time to initialize script
        self.script = commons.ScriptBuilder(self.scriptname)
        self.script.blank_file() # make sure script is blank
        for page in self.pages:
            page.tableau = os.path.join(self.scratch,"tableau_sliced_{SPACE}_{PLANE}.png".format(SPACE=page.infile_basename,PLANE=self.plane))
            self.slicer(page)
        self.png_to_PDF()
        self.final_cleanup(save_intermediates)
        job_spec = commons.JobSpec([self.scriptname],logfile_base,[self.out_pdf])
        return job_spec

    def set_out_pdf_name(self,name,overwrite):
        # sets out pdf name so that output checking can be done beforehand
        pdf_fname = '{sub}_{name}'.format(sub=self.conf.iproc.SUB,name=name)
        pdf_fname += '_{}'.format(self.plane)
        self.scriptname = os.path.join(self.outdir,pdf_fname + '.sh')
        pdf_fname += '.pdf'
        out_pdf = os.path.join(self.outdir,pdf_fname)
        self.out_pdf = out_pdf
        if not overwrite and os.path.exists(out_pdf):
            logger.debug('overwrite set to False and {} exists. SKIPPING'.format(out_pdf))
            return False
        else:
            logger.debug('overwrite set to True or {} does not exist. RUNNING'.format(out_pdf))
            return True

    def slicer(self,page):

        sliced = os.path.join(self.scratch,"tile_sliced_{SPACE}_{PLANE}.png".format(SPACE=page.infile_basename,PLANE=self.plane))

        # make swap nifti with plane-approptiate orientation
        infile = page.infile #T1, e.g. mpr_reorient
        tmpfile = os.path.join(self.scratch, '{}_fslreorient2std.nii.gz'.format(page.infile_basename))
        fslreorient2std_cmd = ['fslreorient2std', infile, tmpfile]
        self.script.append(fslreorient2std_cmd)
        swap = os.path.join(self.scratch,"{SPACE}_swapped_{PLANE}.nii.gz".format(SPACE=page.infile_basename,PLANE=self.plane))
        roi = os.path.join(self.scratch,"{SPACE}_roi_{PLANE}.nii.gz".format(SPACE=page.infile_basename,PLANE=self.plane))
        swapdim_cmd = ['fslswapdim', tmpfile] + self.swapdims + [swap]
        self.script.append(swapdim_cmd)
        
        # extract sub page of nifti 
        window_dims = page.slicer['window_dims']
        fslroi_cmd = ['fslroi', swap, roi] + window_dims
        self.script.append(fslroi_cmd)

        #slice the image and put slices together as tiles in a png image
        sample = page.slicer['sample']
        width = str(page.slicer['width']*180)
        slicer_cmd = ['slicer', roi, '-u', '-S', sample, width, sliced]
        self.script.append(slicer_cmd)

        label = page.infile_basename+ '_'+ self.plane
        # add label
        font = self.conf.get('iproc', 'font')
        if not font:
            logger.info('no iproc.font in user config, trying Nimbus-Sans-Regular')
            font = 'Nimbus-Sans-Regular'
        append_cmd = ['convert', sliced, '-font', font, '-background', 'White', '-pointsize', '20',
                    'label:{}'.format(label), '+swap', '-gravity', 'North-West',
                    '-append', page.tableau]
        
        self.script.append(append_cmd)

    def png_to_PDF(self):
        # converts tableau png in page to pdf
        # ImageMagick 'convert' can exit non-zero (policy warnings, font
        # fallback, etc.) even when the output PDF was written successfully.
        # Disable errexit around the convert, then assert the PDF exists
        # and is non-empty as the actual success criterion.
        tableau_files = [page.tableau for page in self.pages]
        self.script.append(['set', '+e'])
        combine_png_cmd = ['convert', '-adjoin'] + tableau_files + [self.out_pdf]
        self.script.append(combine_png_cmd)
        self.script.append(['set', '-e'])
        self.script.append(['test', '-s', self.out_pdf])

    def final_cleanup(self,save_intermediates):
        if save_intermediates:
            rmcmd = ['#rm', '-rf', self.scratch]
        else:
            rmcmd = ['rm', '-rf', self.scratch]
            logger.debug('intermediate files will not be removed from {}'.format(self.scratch))
        self.script.append(rmcmd)
    ## Helpers
    def _io_file_fmt(self):
        outfile_base = os.path.join(self.conf.iproc.LOGDIR,
                "{SUB}_QC_PDF".format(
                SUB=self.conf.iproc.SUB))
        return outfile_base
  
