from __future__ import absolute_import, division, print_function

import warnings
warnings.filterwarnings("ignore")
import time

class Bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

from dxtbx.model import Panel, Detector
import os

try:
    import pandas
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
from numpy import mean, median, unique, std
from scipy.stats import pearsonr
from numpy import log as np_log
from numpy import sin as SIN
from numpy import cos as COS
from numpy import arcsin as ASIN
from numpy import exp as np_exp
from numpy import load as np_load
from numpy import abs as ABS
from numpy import save as SAVE
from numpy import savez as SAVEZ
from numpy.linalg import norm
from numpy import ones_like as ONES_LIKE
from numpy import where as WHERE
from numpy import sqrt as SQRT
from numpy import array as ARRAY
from numpy import pi as PI
from numpy import allclose as ALL_CLOSE
from json import dump as JSON_DUMP
from os import makedirs as MAKEDIRS
from os.path import exists as EXISTS
from os.path import join as PATHJOIN
from simtbx.diffBragg.refiners import BreakToUseCurvatures
from scitbx.array_family import flex
from cctbx.array_family import flex as cctbx_flex
from numpy import nan as NAN
flex_miller_index = cctbx_flex.miller_index
flex_double = flex.double
FLEX_BOOL = flex.bool
from scitbx.matrix import col
from simtbx.diffBragg.refiners import PixelRefinement
from scipy.optimize import minimize
from collections import Counter
import pylab as plt

# TODO move me to broadcasts
import warnings
from copy import deepcopy
from simtbx.diffBragg.utils import compare_with_ground_truth
from cctbx import miller, sgtbx
import itertools
warnings.filterwarnings("ignore")


class LocalRefiner(PixelRefinement):

    def __init__(self, n_total_params, n_local_params, n_global_params, local_idx_start,
                 shot_ucell_managers, shot_rois, shot_nanoBragg_rois,
                 shot_roi_imgs, shot_spectra, shot_crystal_GTs,
                 shot_crystal_models, shot_xrel, shot_yrel, shot_abc_inits, shot_asu,
                 global_param_idx_start,
                 shot_panel_ids,
                 log_of_init_crystal_scales=None,
                 all_crystal_scales=None, init_gain=1, perturb_fcell=False,
                 global_ncells=False, global_ucell=True, global_originZ=True,
                 shot_originZ_init=None,
                 sgsymbol="P43212",
                 omega_kahn=None, selection_flags=None, shot_bg_coef=None, background_estimate=None,
                 verbose=False):
        """
        TODO: parameter x array boundaries should be done in this class, eliminating the need for local_idx_start
        TODO and global_idx_start
        TODO: ROI and nanoBragg ROI should be single variable

        :param n_total_params:  total number of parameters all shots
        :param n_local_params:  total number of parameters for each shot  (e.g. xtal rotation matrices)
        :param n_global_params: total number of parameters used by all shots (e.g. Fhkl)
        :param local_idx_start: for each shot, this specifies the starting point of its local parameters

        THE FOLLOWING ARE DICTIONARIES WHOSE KEYS ARE SHOT INDICES LOCAL TO THE RANK
        :param shot_ucell_managers: for each shot we have a unit cell manager , from crystal systems folder
        :param shot_rois: for each shot we have the list of ROIs [(x1,x2,y1,y2), .. ]
        :param shot_nanoBragg_rois:  for each shot we have list of ROIS in nanoBRagg format [[(x1,x2+1),(y1,y2+1)] , ...
        :param shot_roi_imgs: for each shot we have the data in each ROI
        :param shot_spectra: for each shot we have the spectra
        :param shot_crystal_GTs:  for each shot we have the ground truht crystal model (or None)
        :param shot_crystal_models: for each shot we have the crystal models
        :param shot_xrel: for each shot we have the relative fast scan coord of each pixel
        :param shot_yrel: for each shot we have relative slow scan coord of each pixel
        :param shot_abc_inits: for each shot we have the a,b,c values of the tilt plane
        :param shot_asu: for each shot we have the ASU miller index for each shoebox
        :param global_param_idx_start: This is position on x array where global parameters begin
        :param shot_panel_ids: for each shot we have panel IDs for each shoebox
        :param log_of_init_crystal_scales: for each shot we have crystal scale factors ( log)
        :param all_crystal_scales: for each shot we have ground truth scale factors (or None)
        :param init_gain: we have init gain correction estimate
        :param perturb_fcell: deprecated, leave as False
        :param global_ncells: do we refine ncells_abc per shot or global for all shots  (global_ncells=True)
        :param global_ucell: do we refine a unitcell per shot or global for all shots (global_ucell=True)
        :param shot_originZ_init: per shot origin Z
        :param global_originZ: do we refine a single detector Z position for all shots (default is True)
        :param omega_kahn: omega and kahn correction term for each panel
        """
        PixelRefinement.__init__(self)
        self.rank = 0
        self.num_kludge = 0
        self.global_ncells_param = global_ncells
        self.global_ucell_param = global_ucell
        self.global_originZ_param = global_originZ
        self.debug = False
        self.num_Fcell_kludge = 0
        self.perturb_fcell = perturb_fcell
        # dictionaries whose keys are the shot indices
        self.UCELL_MAN = shot_ucell_managers
        self.CRYSTAL_SCALE_TRUTH = all_crystal_scales  # ground truth of crystal scale factors..
        # cache shot ids and make sure they are identical in all other input dicts
        self.shot_ids = sorted(shot_ucell_managers.keys())
        self.big_dump = False
        self.show_watched = False
        self.n_shots = len(self.shot_ids)
        self.init_image_corr = None
        self.image_corr = {i_shot:None for i_shot in range(self.n_shots)}
        self.image_corr_norm = {i_shot:None for i_shot in range(self.n_shots)}
        self.shot_originZ_init = None
        if shot_originZ_init is not None:
            if self.verbose:
                print("check originZ")
            self.shot_originZ_init = self._check_keys(shot_originZ_init)
        # load the background coefficient  and extracted backgorund estimate
        self.shot_bg_coef = None
        if shot_bg_coef is not None:
            self.shot_bg_coef = self._check_keys(shot_bg_coef)
        self.background_estimate = background_estimate

        self.selection_flags = selection_flags
        if self.selection_flags is not None:
            if verbose:
                print("check selection flags")
            self.selection_flags = self._check_keys(self.selection_flags)

        # sanity check: no repeats of the same shot
        assert len(self.shot_ids) == len(set(self.shot_ids))

        self.OMEGA_KAHN = omega_kahn
        if verbose:
            print("check ROIS")
        self.ROIS = self._check_keys(shot_rois)
        if verbose:
            print("check ASU")
        self.ASU = self._check_keys(shot_asu)
        if verbose:
            print("check nanoBRAGG ROIS")
        self.NANOBRAGG_ROIS = self._check_keys(shot_nanoBragg_rois)
        if verbose:
            print("check ROI IMAGES")
        self.ROI_IMGS = self._check_keys(shot_roi_imgs)
        if verbose:
            print("check SPECTRA")
        self.SPECTRA = self._check_keys(shot_spectra)
        self.CRYSTAL_GT = None
        if shot_crystal_GTs is not None:
            if verbose:
                print("check GT CRYSTAL")
            self.CRYSTAL_GT = self._check_keys(shot_crystal_GTs)
        if verbose:
            print("check CRYSTAL")
        self.CRYSTAL_MODELS = self._check_keys(shot_crystal_models)
        if verbose:
            print("check XREL YREL")

        self.XREL = self._check_keys(shot_xrel)
        self.YREL = self._check_keys(shot_yrel)
        if verbose:
            print("check ABC INIT")
        self.ABC_INIT = self._check_keys(shot_abc_inits)
        if verbose:
            print("check PANEL IDS")
        self.PANEL_IDS = self._check_keys(shot_panel_ids)

        # Total number of parameters in the MPI world
        self.n_total_params = n_total_params

        # total number of local parameters
        self.n_local_params = n_local_params

        # total number of params varying globally across all shots
        self.n_global_params = n_global_params

        # here are the indices of the local parameters in the global paramter arrays
        self.local_idx_start = local_idx_start

        self.calc_func = True  # NOTE: leave True, debug flag from older code
        self.multi_panel = True  # we are multi panel for all space and time back to the dawn of creation
        self.f_vals = []  # store the functional over time

        # start with the first shot
        self._i_shot = self.shot_ids[0]

        # These are the per-shot parameters
        self.n_rot_param = 3
        self.n_spot_scale_param = 1
        self.n_ucell_param = len(self.UCELL_MAN[self._i_shot].variables)
        self.n_ncells_param = 1

        self.n_per_shot_originZ_param = 1
        if global_originZ:
            self.n_per_shot_originZ_param = 0
        else:
            assert shot_originZ_init is not None

        self.n_per_shot_ucell_param = self.n_ucell_param
        if global_ucell:
            self.n_per_shot_ucell_param = 0

        self.n_per_shot_ncells_param = 1
        if global_ncells:
            self.n_per_shot_ncells_param = 0

        self.n_per_shot_params = self.n_rot_param + self.n_spot_scale_param \
                                 + self.n_per_shot_ncells_param + self.n_per_shot_ucell_param \
                                 + self.n_per_shot_originZ_param

        self._ncells_id = 9  # diffBragg internal index for Ncells derivative manager
        self._originZ_id = 10  # diffBragg internal index for originZ derivative manager
        self._panelRot_id = 14  # diffBragg internal index for originZ derivative manager
        self._panelX_id = 15  # diffBragg internal index for originZ derivative manager
        self._panelY_id = 16  # diffBragg internal index for originZ derivative manager
        self._fcell_id = 11  # diffBragg internal index for Fcell derivative manager
        self._lambda0_id = 12  # diffBragg interneal index for lambda derivatives
        self._lambda1_id = 13  # diffBragg interneal index for lambda derivatives

        if log_of_init_crystal_scales is None:
            log_of_init_crystal_scales = {s: 0 for s in self.shot_ids}
        else:
            assert sorted(log_of_init_crystal_scales.keys()) == self.shot_ids
        self.log_of_init_crystal_scales = log_of_init_crystal_scales

        self._init_gain = init_gain
        self.num_positive_curvatures = 0
        self._panel_id = None
        self.symbol = sgsymbol
        self.space_group = sgtbx.space_group(sgtbx.space_group_info(symbol=self.symbol).type().hall_symbol())

        self.pid_from_idx = {}
        self.idx_from_pid = {}

        self.idx_from_asu = {}
        self.asu_from_idx = {}

        # For priors, use these ..  experimental
        # TODO: update this for general case (once it is actually working to begin with.. )
        self.ave_ucell = [78.95, 38.12]  ## Angstrom
        self.sig_ucell = [0.025, 0.025]
        self.sig_rot = 0.01  # radian

        # where the global parameters being , initially just gain and detector distance
        self.global_param_idx_start = global_param_idx_start

        self.a = self.b = self.c = None  # tilt plan place holder

        # optional properties
        self.FNAMES = None
        self.PROC_FNAMES = None
        self.init_ang_off = None
        self.current_ang_off = None  # TODO move me to pixel_refinement
        self.I_AM_ROOT = True

    def setup_plots(self):
        if self.plot_images:
            if self.plot_residuals:
                from mpl_toolkits.mplot3d import Axes3D
                self.fig = plt.figure()
                self.ax = self.fig.gca(projection='3d')
                self.ax.set_yticklabels([])
                self.ax.set_xticklabels([])
                self.ax.set_zticklabels([])
                self.ax.set_zlabel("model residual")
                self.ax.set_facecolor("gray")
            else:
                self.fig, (self.ax1, self.ax2) = plt.subplots(nrows=1, ncols=2)
                self.ax1.imshow([[0, 1, 1], [0, 1, 2]])  # dummie plot
                self.ax2.imshow([[0, 1, 1], [0, 1, 2]])

    def __call__(self, *args, **kwargs):
        _, _ = self.compute_functional_and_gradients()
        return self.x, self._f, self._g, self.d  #NOTEX

    @property
    def n(self):
        """LBFGS property"""
        return len(self.x)  # NOTEX
        #return self.n_total_params

    @property
    def n_global_fcell(self):
        return len(self.idx_from_asu)

    @property
    def x_for_lbfgs(self):
        """LBFGS parameter array"""
        if self.only_pass_refined_x_to_lbfgs:
            return self.Xall.select(self.is_being_refined)
        else:
            return self.Xall

    @property
    def g_for_lbfgs(self):
        """LBFGS parameter array"""
        if self.only_pass_refined_x_to_lbfgs:
            return self.grad.select(self.is_being_refined)
        else:
            return self.grad

    @property
    def d_for_lbfgs(self):
        """LBFGS parameter array"""
        if self.only_pass_refined_x_to_lbfgs:
            return self.curv.select(self.is_being_refined)
        else:
            return self.curv

    @property
    def x(self):
        """LBFGS parameter array"""
        return self._x

    @x.setter
    def x(self, val):
        self._x = val

    def _check_keys(self, shot_dict):
        """checks that the dictionary keys are the same"""
        if not sorted(shot_dict.keys()) == self.shot_ids:
            raise KeyError("input data funky, check GlobalRefiner inputs")
        return shot_dict

    def _evaluate_averageI(self):
        """model_Lambda means expected intensity in the pixel"""
        self.model_Lambda = \
            self.gain_fac * self.gain_fac * (self.tilt_plane + self.model_bragg_spots)

    def _MPI_make_output_dir(self):
        if self.I_AM_ROOT and self.output_dir is not None and not EXISTS(self.output_dir):
            MAKEDIRS(self.output_dir)

    def _setup(self):
        # Here we go!  https://youtu.be/7VvkXA6xpqI
        if self.I_AM_ROOT:
            print("Setup begins!")
        if not self.asu_from_idx:
            raise ValueError("Need to supply a non empty asu from idx map")
        if not self.idx_from_asu:  # # TODO just derive from its inverse
            raise ValueError("Need to supply a non empty idx from asu map")

        self._MPI_make_output_dir()

        # get the Fhkl information from P1 array internal to nanoBragg
        if self.I_AM_ROOT:
            print("--0 create an Fcell mapping")
        idx, data = self.S.D.Fhkl_tuple
        self.idx_from_p1 = {h: i for i, h in enumerate(idx)}
        # self.p1_from_idx = {i: h for i, h in zip(idx, data)}

        # Make a mapping of panel id to parameter index and backwards
        self.pid_from_idx = {}
        self.idx_from_pid = {}

        # Make the global sized parameter array, though here we only update the local portion
        self.Xall = flex_double(self.n_total_params)
        self.is_being_refined = FLEX_BOOL(self.n_total_params, False)

        # store the starting positions in the parameter array for this shot
        self.rotX_xpos = {}
        self.rotY_xpos = {}
        self.rotZ_xpos = {}
        self.ucell_xstart = {}
        self.ncells_xstart = {}
        self.originZ_xpos = {}
        self.spot_scale_xpos = {}
        self.n_panels = {}
        self.bg_a_xstart = {}
        self.bg_b_xstart = {}
        self.bg_c_xstart = {}
        self.bg_coef_xpos = {}
        if self.I_AM_ROOT:
            print("--1 Setting up per shot parameters")

        # this is a sliding parameter that points to the latest local (per-shot) parameter in the x-array
        _local_pos = self.local_idx_start
        for i_shot in self.shot_ids:
            self.pid_from_idx[i_shot] = {i: pid for i, pid in enumerate(unique(self.PANEL_IDS[i_shot]))}
            self.idx_from_pid[i_shot] = {pid: i for i, pid in enumerate(unique(self.PANEL_IDS[i_shot]))}
            self.n_panels[i_shot] = len(self.pid_from_idx[i_shot])

            if self.bg_extracted:
                self.bg_coef_xpos[i_shot] = _local_pos
                self.Xall[self.bg_coef_xpos[i_shot]] = 1
                if not self.rescale_params:
                    raise NotImplementedError("bg coef mode only works in rescale mode")
                if self.refine_background_planes:
                    self.is_being_refined[self.bg_coef_xpos[i_shot]] = True
            else:
                n_spots = len(self.NANOBRAGG_ROIS[i_shot])
                self.bg_a_xstart[i_shot] = []
                self.bg_b_xstart[i_shot] = []
                self.bg_c_xstart[i_shot] = []
                _spot_start = _local_pos

                for i_spot in range(n_spots):
                    self.bg_a_xstart[i_shot].append(_spot_start)
                    self.bg_b_xstart[i_shot].append(self.bg_a_xstart[i_shot][i_spot] + 1)
                    self.bg_c_xstart[i_shot].append(self.bg_b_xstart[i_shot][i_spot] + 1)

                    a, b, c = self.ABC_INIT[i_shot][i_spot]
                    if self.bg_offset_only and self.bg_offset_positive:
                        if c < 0:
                            c = np_log(1e-9)
                        else:
                            c = np_log(c)
                    if self.rescale_params:
                        self.Xall[self.bg_a_xstart[i_shot][i_spot]] = 1
                        self.Xall[self.bg_b_xstart[i_shot][i_spot]] = 1
                        self.Xall[self.bg_c_xstart[i_shot][i_spot]] = 1

                    else:
                        self.Xall[self.bg_a_xstart[i_shot][i_spot]] = float(a)
                        self.Xall[self.bg_b_xstart[i_shot][i_spot]] = float(b)
                        self.Xall[self.bg_c_xstart[i_shot][i_spot]] = float(c)

                    _spot_start += 3
                    if self.refine_background_planes:
                        self.is_being_refined[self.bg_c_xstart[i_shot][i_spot]] = True
                        if not self.bg_offset_only:
                            self.is_being_refined[self.bg_a_xstart[i_shot][i_spot]] = True
                            self.is_being_refined[self.bg_b_xstart[i_shot][i_spot]] = True

            if self.bg_extracted:
                self.rotX_xpos[i_shot] = self.bg_coef_xpos[i_shot] + 1
            else:
                self.rotX_xpos[i_shot] = self.bg_c_xstart[i_shot][-1] + 1
            self.rotY_xpos[i_shot] = self.rotX_xpos[i_shot] + 1
            self.rotZ_xpos[i_shot] = self.rotY_xpos[i_shot] + 1

            if self.rescale_params:
                self.Xall[self.rotX_xpos[i_shot]] = 1
                self.Xall[self.rotY_xpos[i_shot]] = 1
                self.Xall[self.rotZ_xpos[i_shot]] = 1
            else:
                self.Xall[self.rotX_xpos[i_shot]] = 0
                self.Xall[self.rotY_xpos[i_shot]] = 0
                self.Xall[self.rotZ_xpos[i_shot]] = 0
            if self.refine_Umatrix:
                if self.refine_rotX:
                    self.is_being_refined[self.rotX_xpos[i_shot]] = True
                if self.refine_rotY:
                    self.is_being_refined[self.rotY_xpos[i_shot]] = True
                if self.refine_rotZ:
                    self.is_being_refined[self.rotZ_xpos[i_shot]] = True

            # continue adding local per shot parameters after rotZ_xpos
            _local_pos = self.rotZ_xpos[i_shot] + 1

            # global always starts here, we have to decide whether to put ncells / unit cell/ originZ parameters in global array
            _global_pos = self.global_param_idx_start

            if self.global_ucell_param:
                self.ucell_xstart[i_shot] = _global_pos
                _global_pos += self.n_ucell_param
            else:
                self.ucell_xstart[i_shot] = _local_pos
                _local_pos += self.n_ucell_param
                for i_cell in range(self.n_ucell_param):
                    if self.rescale_params:
                        self.Xall[self.ucell_xstart[i_shot] + i_cell] = 1  #self.UCELL_MAN[i_shot].variables[i_cell]
                    else:
                        self.Xall[self.ucell_xstart[i_shot] + i_cell] = self.UCELL_MAN[i_shot].variables[i_cell]
            # set refinement flags
            if self.refine_Bmatrix:
                for i_cell in range(self.n_ucell_param):
                    self.is_being_refined[self.ucell_xstart[i_shot] + i_cell] = True


            if self.global_ncells_param:
                self.ncells_xstart[i_shot] = _global_pos
                _global_pos += self.n_ncells_param
            else:
                self.ncells_xstart[i_shot] = _local_pos
                _local_pos += self.n_ncells_param
                for i_ncells in range(self.n_ncells_param):
                    ncells_xval = np_log(self.S.crystal.Ncells_abc[i_ncells]-3)
                    # TODO: each shot gets own starting Ncells
                    if self.rescale_params:
                        self.Xall[self.ncells_xstart[i_shot] + i_ncells] = 1
                    else:
                        self.Xall[self.ncells_xstart[i_shot] + i_ncells] = ncells_xval
            # set refinement flags
            if self.refine_ncells:
                for i_ncells in range(self.n_ncells_param):  # note n_ncells_param is always 1 currently
                    self.is_being_refined[self.ncells_xstart[i_shot] + i_ncells] = True

            if self.global_originZ_param:
                self.originZ_xpos[i_shot] = _global_pos
                _global_pos += 1
            else:
                self.originZ_xpos[i_shot] = _local_pos
                _local_pos += 1
                if self.rescale_params:
                    self.Xall[self.originZ_xpos[i_shot]] = 1
                else:
                    self.Xall[self.originZ_xpos[i_shot]] = self.shot_originZ_init[i_shot]
            # set refinement flag
            if self.refine_detdist:
                self.is_being_refined[self.originZ_xpos[i_shot]] = True

            self.spot_scale_xpos[i_shot] = _local_pos
            _local_pos += 1
            if self.rescale_params:
                self.Xall[self.spot_scale_xpos[i_shot]] = 1
            else:
                self.Xall[self.spot_scale_xpos[i_shot]] = self.log_of_init_crystal_scales[i_shot]
            if self.refine_crystal_scale:
                self.is_being_refined[self.spot_scale_xpos[i_shot]] = True

        self.fcell_xstart = _global_pos

        self.spectra_coef_xstart = self.fcell_xstart + self.n_global_fcell

        self.panelRot_xstart = self.spectra_coef_xstart + self.n_spectra_param

        self.panelXY_xstart = self.panelRot_xstart + self.n_panel_rot_param

        self.gain_xpos = self.n_total_params - 1

        # tally up HKL multiplicity
        if self.I_AM_ROOT:
            print("REduction of global data layout")
        self.hkl_totals = []
        fname_totals = []
        panel_id_totals = []
        # img_totals = []
        for i_shot in self.ASU:
            for i_h, h in enumerate(self.ASU[i_shot]):
                if self.FNAMES is not None:
                    fname_totals.append(self.FNAMES[i_shot])
                panel_id_totals.append(self.PANEL_IDS[i_shot][i_h])
                self.hkl_totals.append(self.idx_from_asu[h])
                # img_totals.append(self.ROI_IMGS[i_shot][i_h])
        self.hkl_totals = self._MPI_reduce_broadcast(self.hkl_totals)

        self._MPI_setup_global_params()

        self._MPI_sync_fcell_parameters()

        # reduce then broadcast fcell
        if self.I_AM_ROOT == 0:
            print("--3 combining parameters across ranks")

        self.Xall = self._MPI_reduce_broadcast(self.Xall)

        # flex bool has no + operator so we convert to numpy
        self.is_being_refined = self._MPI_reduce_broadcast(self.is_being_refined.as_numpy_array())
        self.is_being_refined = FLEX_BOOL(self.is_being_refined)

        # set the BFGS parameter array
        self.x = self.x_for_lbfgs

        # make the mapping from x to Xall
        refine_pos = WHERE(self.is_being_refined.as_numpy_array())[0]
        self.x2xall = {xi: xalli for xi, xalli in enumerate(refine_pos)}
        self.xall2x = {xalli: xi for xi, xalli in enumerate(refine_pos)}

        self._MPI_sync_hkl_freq()

        # See if restarting from save state

        if self.x_init is not None: #NOTEX
            self.Xall = self.x_init
            self.x = self.x_for_lbfgs
        elif self.restart_file is not None:
            self.Xall = flex_double(np_load(self.restart_file)["x"])
            self.x = self.x_for_lbfgs

        if self.I_AM_ROOT:
            print("--4 print initial stats")
        rotx, roty, rotz, uc_vals, ncells_vals, scale_vals, _, origZ = self._unpack_internal(self.Xall, lst_is_x=True)
        if self.I_AM_ROOT and self.big_dump and HAS_PANDAS:

            master_data = {"a": uc_vals[0], "c": uc_vals[1],
                           "Ncells": ncells_vals,
                           "scale": scale_vals,
                           "rotx": rotx,
                           "roty": roty,
                           "rotz": rotz,
                           "origZ": origZ}
            master_data = pandas.DataFrame(master_data)
            master_data["gain"] = self.Xall[self.gain_xpos]
            print(master_data.to_string())

        # make the parameter masks for isolating parameters of different types
        self._make_parameter_type_selection_arrays()

        if self.output_dir is not None:
            self._make_x_identifier_array()

        #self._setup_resolution_binner()
        # setup the diffBragg instance
        self.D = self.S.D

        if self.refine_Umatrix:
            if self.refine_rotX:
                self.D.refine(0)  # rotX
            if self.refine_rotY:
                self.D.refine(1)  # rotY
            if self.refine_rotZ:
                self.D.refine(2)  # rotZ
        if self.refine_Bmatrix:
            for i in range(self.n_ucell_param):
                self.D.refine(i + 3)  # unit cell params
        if self.refine_ncells:
            self.D.refine(self._ncells_id)
        if self.refine_detdist:
            self.D.refine(self._originZ_id)
        if self.refine_panelRot:
            self.D.refine(self._panelRot_id)
        if self.refine_panelXY:
            self.D.refine(self._panelX_id)
            self.D.refine(self._panelY_id)
        if self.refine_Fcell:
            self.D.refine(self._fcell_id)
        if self.refine_lambda0:
            self.D.refine(self._lambda0_id)
        if self.refine_lambda1:
            self.D.refine(self._lambda1_id)
        self.D.initialize_managers()

    def _MPI_setup_global_params(self):
        if self.I_AM_ROOT:
            print("--2 Setting up global parameters")
            # put in estimates for origin vectors
            # TODO: refine at the different hierarchy
            # get te first Z coordinate for now..
            # print("Setting origin: %f " % self.S.detector[0].get_local_origin()[2])
            if self.global_ucell_param:
                # TODO have parameter for global init of unit cell, right now its handled in the global_bboxes scripts
                for i_cell in range(self.n_ucell_param):
                    if self.rescale_params:
                        self.Xall[self.ucell_xstart[0] + i_cell] = 1
                    else:
                        self.Xall[self.ucell_xstart[0] + i_cell] = self.UCELL_MAN[0].variables[i_cell]

            if self.global_ncells_param:
                # TODO have parameter for global init of Ncells , right now its handled in the global_bboxes scripts
                for i_ncells in range(self.n_ncells_param):
                    if self.rescale_params:
                        ncells_xval = 1
                    else:
                        ncells_xval = np_log(self.S.crystal.Ncells_abc[i_ncells] - 3)
                    self.Xall[self.ncells_xstart[0] + i_ncells] = ncells_xval

            if self.global_originZ_param:
                # TODO have parameter for global init of originZ param , right now its handled in the global_bboxes scripts
                if self.rescale_params:
                    self.Xall[self.originZ_xpos[
                        0]] = 1  # self.S.detector[0].get_local_origin()[2]  # NOTE maybe just origin instead?elf.S.detector
                else:
                    self.Xall[self.originZ_xpos[0]] = self.S.detector[0].get_origin()[
                        2]  # NOTE maybe just origin instead?elf.S.detector
                    # self.Xall[self.originZ_xpos[0]] = self.S.detector[0].get_local_origin()[2]  # NOTE maybe just origin instead?elf.S.detector

            # if self.refine_lambda0 or self.refine_lambda1:
            lambda_is_refined = self.refine_lambda0, self.refine_lambda1
            for i_spec_coef in range(self.n_spectra_param):
                xpos = self.spectra_coef_xstart + i_spec_coef
                self.is_being_refined[xpos] = lambda_is_refined[i_spec_coef]
                self.Xall[xpos] = 1
                if not self.rescale_params:
                    raise NotImplementedError("Cant refine spectra without rescale_params=True")

            for i_pan_rot in range(self.n_panel_rot_param):
                xpos = self.panelRot_xstart + i_pan_rot
                if self.refine_panelRot:
                    assert self.rescale_params
                    self.is_being_refined[xpos] = True
                self.Xall[xpos] = 1

            for i_pan_XY in range(self.n_panel_XY_param):
                xpos = self.panelXY_xstart + i_pan_XY
                # xpos_Y = self.panelXY_xstart + 2*i_pan_XY + 1
                self.Xall[xpos] = 1
                # self.Xall[xpos_Y] = 1
                if self.refine_panelXY:
                    assert self.rescale_params
                    self.is_being_refined[xpos] = True
                    # self.is_being_refined[xpos_Y] = True

            print("----loading fcell data")
            # this is the number of observations of hkl (accessed like a dictionary via global_fcell_index)
            print("---- -- counting hkl totes")
            self.hkl_frequency = Counter(self.hkl_totals)

            # initialize the Fhkl global values
            print("--- --- --- inserting the Fhkl array in the parameter array... ")
            asu_idx = [self.asu_from_idx[idx] for idx in range(self.n_global_fcell)]
            self._refinement_millers = flex_miller_index(tuple(asu_idx))
            Findices, Fdata = self.S.D.Fhkl_tuple
            vals = [Fdata[self.idx_from_p1[h]] for h in asu_idx]  # TODO am I correct/
            if self.rescale_params:
                self.fcell_init = deepcopy(vals)  # store the initial values  for rescaling procedure
            if not self.rescale_params and self.log_fcells:
                vals = np_log(vals)
            for i_fcell in range(self.n_global_fcell):
                if self.rescale_params:
                    self.Xall[self.fcell_xstart + i_fcell] = 1
                else:
                    self.Xall[self.fcell_xstart + i_fcell] = vals[i_fcell]
                if self.refine_Fcell:  # TODO only refine if fcell is in the res range
                    self.is_being_refined[self.fcell_xstart + i_fcell] = True

            self.Fref_aligned = self.Fref
            if self.Fref is not None:
                self.Fref_aligned = self.Fref.select_indices(self.Fobs.indices())
                self.init_R1 = self.Fobs_Fref_Rfactor(use_binning=False, auto_scale=self.scale_r1)
                print("Initial R1 = %.4f" % self.init_R1)
            else:
                self.init_R1 = -1

            if self.Fobs is not None:  # TODO should this ever be None ?
                miller_binner = self.Fobs.binner()
                miller_bin_idx = miller_binner.bin_indices()

                import numpy as np  # TODO move me to top
                from simtbx.diffBragg.utils import nearest_non_zero

                unique_bins = sorted(set(miller_bin_idx))
                sigmas = []
                for i_bin in unique_bins:
                    dmax, dmin = miller_binner.bin_d_range(i_bin)
                    f_selection = self.Fobs.resolution_filter(d_min=dmin, d_max=dmax)
                    fsel_data = f_selection.data().as_numpy_array()
                    if self.log_fcells:
                        fsel_data = np_log(fsel_data)
                    sigma = SQRT(mean(f_selection.data().as_numpy_array() ** 2))
                    sigmas.append(sigma)  # sigma_for_res_id[i_bin] = sigma
                # min_sigma = min(self.sigma_for_res_id.values())
                # max_sigma = max(self.sigma_for_res_id.values())
                # median_sigma = np.median(self.sigma_for_res_id.values())
                self.sigma_for_res_id = {}
                summed_sigma = 0
                for ii, sigma in enumerate(sigmas):
                    i_bin = unique_bins[ii]
                    if sigma == 0:
                        sigma = nearest_non_zero(sigmas, ii)
                    if sigma == 0:
                        bin_rng = miller_binner.bin_d_range(i_bin)
                        raise ValueError("sigma is being set to 0 for all fcell in range %.4f - %.4f" % bin_rng)
                    if self.rescale_fcell_by_resolution:
                        assert sigma > 0
                        self.sigma_for_res_id[i_bin] = 1. / sigma
                        summed_sigma += 1. / sigma
                    else:
                        self.sigma_for_res_id[i_bin] = 1.
                if self.rescale_fcell_by_resolution:
                    assert summed_sigma > 0
                    for ii in self.sigma_for_res_id.keys():
                        self.sigma_for_res_id[ii] = self.sigma_for_res_id[ii] / summed_sigma

                print("SIGMA FOR RES ID:")
                print(self.sigma_for_res_id)

                self.res_group_id_from_fcell_index = {}
                for ii, asu_index in enumerate(miller_binner.miller_indices()):
                    if asu_index not in self.idx_from_asu:
                        raise KeyError("something wrong Fobs does not contain the asu indices")
                    i_fcell = self.idx_from_asu[asu_index]
                    self.res_group_id_from_fcell_index[i_fcell] = miller_bin_idx[ii]

            if self.output_dir is not None:
                # np.save(os.path.join(self.output_dir, "f_truth"), self.f_truth)  #FIXME by adding in the correct truth from Fref
                SAVE(os.path.join(self.output_dir, "f_asu_map"), self.asu_from_idx)

            # set gain TODO: implement gain dependent statistical model ? Per panel or per gain mode dependent ?
            self.Xall[self.gain_xpos] = self._init_gain  # gain factor

    def determine_parameter_freeze_order(self):
        param_sels = []
        if self.refine_detdist:
            param_sels.append(self.origin_sel)
        if self.refine_Umatrix:
            param_sels.append(self.umatrix_sel)
        if self.refine_Bmatrix:
            param_sels.append(self.bmatrix_sel)
        if self.refine_Fcell:
            param_sels.append(self.Fcell_sel)
        if self.refine_ncells:
            param_sels.append(self.ncells_sel)
        if self.refine_crystal_scale:
            param_sels.append(self.spot_scale_sel)
        if self.refine_background_planes:
            param_sels.append(self.bg_sel)

        self.param_sels = itertools.cycle(param_sels)

    def _update_Xall_from_x(self):
        """update the master parameter array with values from the parameter array that LBFGS sees"""
        for i, val in enumerate(self.x):
            if self.only_pass_refined_x_to_lbfgs:
                Xall_pos = self.x2xall[i]
            else:
                Xall_pos = i
            self.Xall[Xall_pos] = val
        # TODO maybe its more quick to use set_selected with is_being_refined ?
        # seomthing like self.Xall.set_selected(self.is_being_refined, self.x)

    def _make_x_identifier_array(self):
        """do this in case we need to identify what the parameters in X are at a later time"""
        parameter_dict = {}
        for i_shot in range(self.n_shots):
            if self.FNAMES is None:
                fname = "rank%d_shot%d" % (self.rank, i_shot)
            else:
                fname = self.FNAMES[i_shot]

            proc_fname = "null"
            if self.PROC_FNAMES is not None:
                proc_fname = self.PROC_FNAMES[i_shot]

            proc_idx = -1
            if self.PROC_IDX is not None:
                proc_idx = int(self.PROC_IDX[i_shot])

            img_fname = fname
            parameter_dict[img_fname] = {}
            parameter_dict[img_fname]["agg_file"] = proc_fname
            parameter_dict[img_fname]["agg_idx"] = proc_idx
            parameter_dict[img_fname]["x_pos"] = {}
            PD = parameter_dict[img_fname]["x_pos"]

            # save the background tilt plane coefficients identifiers
            if not self.bg_extracted:
                nspots_on_shot = len(self.NANOBRAGG_ROIS[i_shot])
                for i_roi in range(nspots_on_shot):
                    i_a = self.bg_a_xstart[i_shot][i_roi]
                    i_b = self.bg_b_xstart[i_shot][i_roi]
                    i_c = self.bg_c_xstart[i_shot][i_roi]
                    if self.BBOX_IDX is not None:
                        bbox_idx = self.BBOX_IDX[i_shot][i_roi]
                    else:
                        bbox_idx = -1
                    PD[i_a] = "t1", bbox_idx
                    PD[i_b] = "t2", bbox_idx
                    PD[i_c] = "t3", bbox_idx
            else:
                i_bg_coef = self.bg_coef_xpos[i_shot]
                PD[i_bg_coef] = "bg_coef"

            # save the rotation angles identifier
            i_rotX = self.rotX_xpos[i_shot]
            i_rotY = self.rotY_xpos[i_shot]
            i_rotZ = self.rotZ_xpos[i_shot]
            PD[i_rotX] = "rX"
            PD[i_rotY] = "rY"
            PD[i_rotZ] = "rZ"

            # save unit cell variables identifier
            ucell_man = self.UCELL_MAN[i_shot]
            names = ucell_man.variable_names
            for i_name, name in enumerate(names):
                i_uc = self.ucell_xstart[i_shot] + i_name
                PD[i_uc] = name

            # save the ncells identifier
            if self.n_ncells_param == 1:
                ncells_names = ("m",)
            else:  # only other choice is n_ncells_param=3
                ncells_names = "Na", "Nb", "Nc"
            for i_nc in range(self.n_ncells_param):
                i_ncells = self.ncells_xstart[i_shot] + i_nc
                PD[i_ncells] = ncells_names[i_nc]

            # save spot scale indentifier
            i_scale = self.spot_scale_xpos[i_shot]
            PD[i_scale] = "Gs"

        self._MPI_write_output(parameter_dict)

    def _MPI_write_output(self, parameter_dict):
        if self.output_dir is not None:
            outdir = PATHJOIN(self.output_dir, "parameter_id")
            if self.I_AM_ROOT and not EXISTS(outdir):
                MAKEDIRS(outdir)
            all_data = self._data_for_write(parameter_dict)
            if self.I_AM_ROOT:
                for i_pd, PD in enumerate(all_data):
                    output_path = PATHJOIN(outdir, "param%d.json" % i_pd)
                    with open(output_path, "w") as out:
                        JSON_DUMP(PD, out)

    def _make_parameter_type_selection_arrays(self):  # experimental , not really used
        from cctbx.array_family import flex
        self.umatrix_sel = flex.bool(len(self.Xall), True)
        self.bmatrix_sel = flex.bool(len(self.Xall), True)
        self.Fcell_sel = flex.bool(len(self.Xall), True)
        self.origin_sel = flex.bool(len(self.Xall), True)
        self.spot_scale_sel = flex.bool(len(self.Xall), True)
        self.ncells_sel = flex.bool(len(self.Xall), True)
        self.bg_sel = flex.bool(len(self.Xall), True)
        for i_shot in range(self.n_shots):
            self.umatrix_sel[self.rotX_xpos[i_shot]] = False
            self.umatrix_sel[self.rotY_xpos[i_shot]] = False
            self.umatrix_sel[self.rotZ_xpos[i_shot]] = False

            for i_uc in range(self.n_ucell_param):
                self.bmatrix_sel[self.ucell_xstart[i_shot] + i_uc] = False

            for i_ncells in range(self.n_ncells_param):
                self.ncells_sel[self.ncells_xstart[i_shot] + i_ncells] = False
            self.spot_scale_sel[self.spot_scale_xpos[i_shot]] = False

            self.origin_sel[self.originZ_xpos[i_shot]] = False

            if not self.bg_extracted:
                nspots_on_shot = len(self.NANOBRAGG_ROIS[i_shot])
                for i_spot in range(nspots_on_shot):
                    self.bg_sel[self.bg_a_xstart[i_shot][i_spot]] = False
                    self.bg_sel[self.bg_b_xstart[i_shot][i_spot]] = False
                    self.bg_sel[self.bg_c_xstart[i_shot][i_spot]] = False

        for i_fcell in range(self.n_global_fcell):
            self.Fcell_sel[self.fcell_xstart + i_fcell] = False

    def _get_rotX(self, i_shot):
        if self.rescale_params:
            # FIXME ?
            return self.rotX_sigma*(self.Xall[self.rotX_xpos[i_shot]]-1) + 0.0
        else:
            return self.Xall[self.rotX_xpos[i_shot]]

    def _get_rotY(self, i_shot):
        if self.rescale_params:
            return self.rotY_sigma * (self.Xall[self.rotY_xpos[i_shot]] - 1) + 0.0
        else:
            return self.Xall[self.rotY_xpos[i_shot]]

    def _get_rotZ(self, i_shot):
        if self.rescale_params:
            return self.rotZ_sigma * (self.Xall[self.rotZ_xpos[i_shot]] - 1) + 0.0
        else:
            return self.Xall[self.rotZ_xpos[i_shot]]

    def _get_spectra_coefficients(self):
        vals = []
        if self.rescale_params:
            for i in range(self.n_spectra_param):
                xval = self.Xall[self.spectra_coef_xstart + i]
                sig = self.spectra_coefficients_sigma[i]
                init = self.spectra_coefficients_init[i]
                low, high = self.lambda_coef_ranges[i]
                rng = high-low
                sin_arg = sig*(xval-1) + ASIN(2*(init-low)/rng - 1)
                val = (SIN(sin_arg) + 1)*rng/2 + low
                #val = sig*(xval-1) + init
                vals.append(val)
        else:
            assert NotImplementedError
        return vals

    def _get_ucell_vars(self, i_shot):
        all_p = []
        for i in range(self.n_ucell_param):
            if self.rescale_params:
                sig = self.ucell_sigmas[i]
                init = self.ucell_inits[i_shot][i]
                p = sig*(self.Xall[self.ucell_xstart[i_shot]+i] - 1) + init
            else:
                p = self.Xall[self.ucell_xstart[i_shot]+i]
            all_p.append(p)
        return all_p

    def _get_panelRot_val(self, panel_id):
        if self.n_panel_rot_param == 0:
            return
        panel_group_id = self.panel_group_from_id[panel_id]
        val = self.Xall[self.panelRot_xstart + panel_group_id]
        sig = self.panelRot_sigma
        init = self.panelRot_init[panel_group_id]
        val = sig*(val-1) + init
        return val

    def _get_panelXY_val(self, panel_id):
        if self.n_panel_XY_param == 0:
            return

        panel_group_id = self.panel_group_from_id[panel_id]

        xpos_X = self.panelXY_xstart + 2*panel_group_id
        valX = self.Xall[xpos_X]
        sigX = self.panelX_sigma
        initX = self.panelX_init[panel_group_id]
        valX = sigX*(valX-1) + initX

        valY = self.Xall[xpos_X+1]
        sigY = self.panelY_sigma
        initY = self.panelY_init[panel_group_id]
        valY = sigY*(valY-1) + initY

        return valX, valY

    def _get_originZ_val(self, i_shot):
        if not self.refine_detdist:
            return 0 #None

        val = self.Xall[self.originZ_xpos[i_shot]]
        if self.rescale_params:
            sig = self.originZ_sigma
            init = self.shot_originZ_init[i_shot]
            if self.originZ_range is not None:
                low, high = self.originZ_range
                rng = high - low
                sin_arg = sig * (val - 1) + ASIN(2 * (init - low) / rng - 1)
                val = (SIN(sin_arg) + 1) * rng / 2 + low
            else:
                #NOTE old way:
                val = sig*(val-1) + init
            print("<><><><>\nZ=%.4f  %.4f\n><><><><>" % (init, val))
        return val

    def _get_m_val(self, i_shot):
        vals = []
        if self.S.D.isotropic_ncells:
            val = self.Xall[self.ncells_xstart[i_shot]]
            if self.rescale_params:
                sig = self.m_sigma
                init = self.m_init[i_shot]
                val = np_exp(sig*(val-1))*(init-3) + 3
            else:
                val = np_exp(val)+3
            vals.append(val)
        else:
            for i_ncell in range(self.n_ncells_param):
                val = self.Xall[self.ncells_xstart[i_shot] + i_ncell]
                if self.rescale_params:
                    sig = self.m_sigma
                    init = self.m_init[i_shot][i_ncell]
                    val = np_exp(sig * (val - 1)) * (init - 3) + 3
                else:
                    val = np_exp(val) + 3
                vals.append(val)
        return vals

    def _get_spot_scale(self, i_shot):
        val = self.Xall[self.spot_scale_xpos[i_shot]]
        if self.rescale_params:
            sig = self.spot_scale_sigma
            init = self.spot_scale_init[i_shot]
            val = np_exp(sig*(val-1))*init
        else:
            val = np_exp(val)
        return val

    def _get_bg_coef(self, i_shot):
        assert (self.rescale_params)
        val = self.Xall[self.bg_coef_xpos[i_shot]]
        sig = self.bg_coef_sigma
        init = self.shot_bg_coef[i_shot]
        val = np_exp(sig*(val-1))*init
        return val

    def _set_spot_scale(self, new_val, i_shot):
        """just used in testsing derivatives"""
        if self.rescale_params:
            self.spot_scale_init[0] = new_val
            self.Xall[self.spot_scale_xpos[0]] = 1
        else:
            self.Xall[self.spot_scale_xpos[0]] = np_log(new_val)

    def _get_bg_vals(self, i_shot, i_spot):
        a_val = self.Xall[self.bg_a_xstart[i_shot][i_spot]]
        b_val = self.Xall[self.bg_b_xstart[i_shot][i_spot]]
        c_val = self.Xall[self.bg_c_xstart[i_shot][i_spot]]
        if self.rescale_params:
            a_sig = self.a_sigma
            b_sig = self.b_sigma
            c_sig = self.c_sigma
            a_init, b_init, c_init = self.ABC_INIT[i_shot][i_spot]
            a = a_sig*(a_val-1) + a_init
            b = b_sig*(b_val-1) + b_init
            c = c_sig*(c_val-1) + c_init
            if self.bg_offset_positive:
                c = np_exp(c_sig*(c_val-1))*c_init

        elif self.bg_offset_positive:
            a = a_val
            b = b_val
            c = np_exp(c_val)
        else:
            a = a_val
            b = b_val
            c = c_val

        if self.bg_offset_only:
            a = b = 0

        return a, b, c

    def _unpack_internal(self, lst, lst_is_x=False):
        # x = self..as_numpy_array()
        # note n_shots should be specific for this rank
        if lst_is_x:
            rotx = [self._get_rotX(i_shot) for i_shot in range(self.n_shots)]
            roty = [self._get_rotY(i_shot) for i_shot in range(self.n_shots)]
            rotz = [self._get_rotZ(i_shot) for i_shot in range(self.n_shots)]
        else:
            rotx = [lst[self.rotX_xpos[i_shot]] for i_shot in range(self.n_shots)]
            roty = [lst[self.rotY_xpos[i_shot]] for i_shot in range(self.n_shots)]
            rotz = [lst[self.rotZ_xpos[i_shot]] for i_shot in range(self.n_shots)]

        if self.global_ncells_param:
            if lst_is_x:
                ncells_vals = [self._get_m_val(0)[0]] * len(rotx)
            else:
                ncells_vals = [lst[self.ncells_xstart[0]]] * len(rotx)
        else:
            if lst_is_x:
                ncells_vals = [self._get_m_val(i_shot)[0] for i_shot in range(self.n_shots)]
            else:
                ncells_vals = [lst[self.ncells_xstart[i_shot]] for i_shot in range(self.n_shots)]

        if self.global_originZ_param:
            if lst_is_x:
                originZ_vals = [self._get_originZ_val(0)] * len(rotx)
            else:
                originZ_vals = [lst[self.originZ_xpos[0]]] * len(rotx)
        else:
            if lst_is_x:
                originZ_vals = [self._get_originZ_val(i_shot) for i_shot in range(self.n_shots)]
            else:
                originZ_vals = [lst[self.originZ_xpos[i_shot]] for i_shot in range(self.n_shots)]

        if lst_is_x:
            #ncells_vals = list(np_exp(ncells_vals)+3)
            scale_vals = [self._get_spot_scale(i_shot) for i_shot in range(self.n_shots)]
        else:
            scale_vals = [lst[self.spot_scale_xpos[i_shot]] for i_shot in range(self.n_shots)]

        # this can be used to compare directly
        if self.CRYSTAL_SCALE_TRUTH is not None:
            scale_vals_truths = [self.CRYSTAL_SCALE_TRUTH[i_shot] for i_shot in range(self.n_shots)]
        else:
            scale_vals_truths = None

        if self.global_ucell_param:
            if lst_is_x:
                ucparams = self._get_ucell_vars(0)
            else:
                ucparams = lst[self.ucell_xstart[0]:self.ucell_xstart[0] + self.n_ucell_param]
            ucparams_lsts = []
            for ucp in ucparams:
                ucparams_lsts.append([ucp]*len(rotx))
        else:
            if lst_is_x:
                all_shot_params = [self._get_ucell_vars(i_shot) for i_shot in range(self.n_shots)]
                ucparams_lsts = list(map(list, zip(*all_shot_params)))
            else:
                ucparams_lsts = []
                for i_uc in range(self.n_ucell_param):
                    ucp_lst = [lst[self.ucell_xstart[i_shot] + i_uc] for i_shot in range(self.n_shots)]
                    ucparams_lsts.append(ucp_lst)

        rotx = self._MPI_reduce_broadcast(rotx)
        roty = self._MPI_reduce_broadcast(roty)
        rotz = self._MPI_reduce_broadcast(rotz)
        ncells_vals = self._MPI_reduce_broadcast(ncells_vals)
        scale_vals = self._MPI_reduce_broadcast(scale_vals)
        originZ_vals = self._MPI_reduce_broadcast(originZ_vals)

        ucparams_all = []
        for ucp in ucparams_lsts:
            ucp = self._MPI_reduce_broadcast(ucp)
            ucparams_all.append(ucp)
        if scale_vals_truths is not None:
            scale_vals_truths = self._MPI_reduce_broadcast(scale_vals_truths)

        return rotx, roty, rotz, ucparams_all, ncells_vals, scale_vals, scale_vals_truths, originZ_vals

    def _send_ucell_gradients_to_derivative_managers(self):
        """Needs to be called once each time the orientation is updated"""
        for i in range(self.n_ucell_param):
            self.D.set_ucell_derivative_matrix(
                i + 3,
                self.UCELL_MAN[self._i_shot].derivative_matrices[i])
            if self.calc_curvatures:
                self.D.set_ucell_second_derivative_matrix(
                    i + 3, self.UCELL_MAN[self._i_shot].second_derivative_matrices[i])

    def _run_diffBragg_current(self, i_spot):
        """needs to be called each time the ROI is changed"""
        (i1, i2), (j1, j2) = self.NANOBRAGG_ROIS[self._i_shot][i_spot]
        self.D.region_of_interest = (int(i1), int(i2)), (int(j1), int(j2))
        #self.D.printout_pixel_fastslow = int(i1)+2, int(j1)+2
        self.D.add_diffBragg_spots()

    def _get_fcell_val(self, i_fcell):
        # TODO vectorize me
        # i_fcell is between 0 and self.n_global_fcell
        # get the asu index and its updated amplitude
        xpos = self.fcell_xstart + i_fcell
        val = self.Xall[xpos]  # new amplitude
        if self.rescale_params:
            resolution_id = self.res_group_id_from_fcell_index[i_fcell]  # TODO
            sig = self.sigma_for_res_id[resolution_id]*self.fcell_sigma_scale  # TODO
            init = self.fcell_init[i_fcell]
            if self.log_fcells:
                val = np_exp(sig*(val - 1))*init
            else:
                if val < 0:  # NOTE this easily happens without the log c.o.v.
                    self.Xall[xpos] = 0
                    val = 0
                    self.num_Fcell_kludge += 1
                else:
                    val = sig*(val - 1) + init

        else:
            if self.log_fcells:
                val = np_exp(val)
            if val < 0:  # NOTE this easily happens without the log c.o.v.
                self.Xall[xpos] = 0
                val = 0
                self.num_Fcell_kludge += 1
        return val

    def _update_Fcell(self):
        idx, data = self.S.D.Fhkl_tuple
        for i_fcell in range(self.n_global_fcell):
            # get the asu miller index
            hkl_asu = self.asu_from_idx[i_fcell]

            new_Fcell_amplitude = self._get_fcell_val(i_fcell)

            # now surgically update the p1 array in nanoBragg with the new amplitudes
            # (need to update each symmetry equivalent)
            equivs = [i.h() for i in miller.sym_equiv_indices(self.space_group, hkl_asu).indices()] # todo: speed test.
            for h_equiv in equivs:
                # get the nanoBragg p1 miller table index corresponding to this hkl equivalent
                try:
                    p1_idx = self.idx_from_p1[h_equiv]  # TODO change name to be more specific
                except KeyError as err:
                    if self.debug:
                        print( h_equiv, err)
                    continue
                data[p1_idx] = new_Fcell_amplitude  # set the data with the new value
        self.S.D.Fhkl_tuple = idx, data  # update nanoBragg again  # TODO: add flag to not re-allocate in nanoBragg!

    def _update_spectra_coefficients(self):
        if self.refine_lambda0 or self.refine_lambda1:
            coeffs = self._get_spectra_coefficients()
            self.D.lambda_coefficients = tuple(coeffs)

    def _set_background_plane(self, i_spot):
        if self.bg_extracted:
            self.bg_coef = self._get_bg_coef(self._i_shot)
            (i1, i2), (j1, j2) = self.NANOBRAGG_ROIS[self._i_shot][i_spot]
            self.tilt_plane = self.bg_coef*self.background_estimate[self._panel_id, j1:j2+1, i1:i2+1]

        else:
            xr = self.XREL[self._i_shot][i_spot]
            yr = self.YREL[self._i_shot][i_spot]
            self.a, self.b, self.c = self._get_bg_vals(self._i_shot, i_spot)
            if self.bg_offset_only:
                self.tilt_plane = ONES_LIKE(xr)*self.c
            else:
                self.tilt_plane = xr * self.a + yr * self.b + self.c
            if self.OMEGA_KAHN is not None:
                (i1, i2), (j1, j2) = self.NANOBRAGG_ROIS[self._i_shot][i_spot]
                omega_kahn_correction = self.OMEGA_KAHN[self._panel_id][j1:j2+1, i1:i2+1]
                self.tilt_plane *= omega_kahn_correction

    def _update_rotXYZ(self):
        if self.refine_rotX:
            self.D.set_value(0, self._get_rotX(self._i_shot))
        if self.refine_rotY:
            self.D.set_value(1, self._get_rotY(self._i_shot))
        if self.refine_rotZ:
            self.D.set_value(2, self._get_rotZ(self._i_shot))

    def _update_ncells(self):
        vals = self._get_m_val(self._i_shot)
        if self.D.isotropic_ncells:
            self.D.set_value(self._ncells_id, vals[0])
        else:
            self.D.set_ncells_values(tuple(vals))

    def _update_dxtbx_detector(self):
        self.S.panel_id = self._panel_id
        node_dict = self.S.detector[self._panel_id].to_dict()

        orig = node_dict['origin']
        newX = orig[0]
        newY = orig[1]
        newZ = orig[2]

        new_XY = self._get_panelXY_val(self._panel_id)
        if new_XY is not None:
            newX_offset, newY_offset = new_XY
            newX += newX_offset
            newY += newY_offset

        new_originZ = self._get_originZ_val(self._i_shot)
        if new_originZ is not None:
            newZ += new_originZ

        new_origin = newX, newY, newZ

        node_dict["origin"] = new_origin
        node = Panel.from_dict(node_dict)
        new_det = Detector()
        new_det.add_panel(node)
        panel_rot_ang = 0
        if self.refine_panelRot:
            panel_rot_ang = self._get_panelRot_val(self._panel_id)
            assert panel_rot_ang is not None
        self.D.update_dxtbx_geoms(new_det, self.S.beam.nanoBragg_constructor_beam, self._panel_id, panel_rot_ang)
        #if self.recenter:
        #    s0 = self.S.beam.nanoBragg_constructor_beam.get_s0()
        #    assert ALL_CLOSE(node.get_beam_centre(s0), self.D.beam_center_mm)

    def _extract_spectra_coefficient_derivatives(self):
        self.spectra_derivs = [0]*self.n_spectra_param
        if self.refine_lambda0 or self.refine_lambda1:
            SG = self.scale_fac * self.G2
            if self.refine_lambda0:
                self.spectra_derivs[0] = SG*self.D.get_derivative_pixels(12).as_numpy_array()
            if self.refine_lambda1:
                self.spectra_derivs[1] = SG*self.D.get_derivative_pixels(13).as_numpy_array()

    def _extract_Umatrix_derivative_pixels(self):
        self.rotX_dI_dtheta = self.rotY_dI_dtheta = self.rotZ_dI_dtheta = 0
        self.rotX_d2I_dtheta2 = self.rotY_d2I_dtheta2 = self.rotZ_d2I_dtheta2 = 0
        # convenient storage of the gain and scale as a single parameter
        SG = self.scale_fac*self.G2
        if self.refine_Umatrix:
            if self.refine_rotX:
                self.rotX_dI_dtheta = SG*self.D.get_derivative_pixels(0).as_numpy_array()
                if self.calc_curvatures:
                    self.rotX_d2I_dtheta2 = SG*self.D.get_second_derivative_pixels(0).as_numpy_array()

            if self.refine_rotY:
                self.rotY_dI_dtheta = SG*self.D.get_derivative_pixels(1).as_numpy_array()
                if self.calc_curvatures:
                    self.rotY_d2I_dtheta2 = SG*self.D.get_second_derivative_pixels(1).as_numpy_array()

            if self.refine_rotZ:
                self.rotZ_dI_dtheta = SG*self.D.get_derivative_pixels(2).as_numpy_array()
                if self.calc_curvatures:
                    self.rotZ_d2I_dtheta2 = SG*self.D.get_second_derivative_pixels(2).as_numpy_array()

    def _extract_Bmatrix_derivative_pixels(self):
        # the Bmatrix derivatives are stored for each unit cell parameter (UcellManager.variables)
        self.ucell_dI_dtheta = [0] * self.n_ucell_param
        self.ucell_d2I_dtheta2 = [0] * self.n_ucell_param
        SG = self.scale_fac*self.G2
        if self.refine_Bmatrix:
            for i in range(self.n_ucell_param):
                self.ucell_dI_dtheta[i] = SG*self.D.get_derivative_pixels(3 + i).as_numpy_array()
                if self.calc_curvatures:
                    self.ucell_d2I_dtheta2[i] = SG*self.D.get_second_derivative_pixels(3 + i).as_numpy_array()

    def _extract_mosaic_parameter_m_derivative_pixels(self):
        SG = self.scale_fac * self.G2
        if self.D.isotropic_ncells:  # TODO remove need for if/else
            self.m_dI_dtheta = self.m_d2I_dtheta2 = 0
            if self.refine_ncells:
                self.m_dI_dtheta = SG*self.D.get_derivative_pixels(self._ncells_id).as_numpy_array()
                if self.calc_curvatures:
                    self.m_d2I_dtheta2 = SG*self.D.get_second_derivative_pixels(self._ncells_id).as_numpy_array()
            self.m_dI_dtheta = [self.m_dI_dtheta]
            self.m_d2I_dtheta2 = [self.m_d2I_dtheta2]
        else:
            self.m_dI_dtheta = [0] * self.n_ncells_param
            self.m_d2I_dtheta2 = [0] * self.n_ncells_param
            derivs = self.D.get_ncells_derivative_pixels()
            if self.calc_curvatures:
                second_derivs = self.D.get_ncells_second_derivative_pixels()
            for i_ncell in range(self.n_ncells_param):
                d = derivs[i_ncell].as_numpy_array()
                self.m_dI_dtheta[i_ncell] = SG*d
                if self.calc_curvatures:
                    d2 = second_derivs[i_ncell].as_numpy_array()
                    self.m_d2I_dtheta2[i_ncell] = SG*d2

    def _extract_originZ_derivative_pixels(self):
        self.detdist_dI_dtheta = self.detdist_d2I_dtheta2 = 0
        SG = self.scale_fac*self.G2
        if self.refine_detdist:
            self.detdist_dI_dtheta = SG*self.D.get_derivative_pixels(self._originZ_id).as_numpy_array()
            if self.calc_curvatures:
                self.detdist_d2I_dtheta2 = SG*self.D.get_second_derivative_pixels(self._originZ_id).as_numpy_array()

    def _extract_panelRot_derivative_pixels(self):
        self.panelRot_dI_dtheta = self.panelRot_d2I_dtheta2 = 0
        SG = self.scale_fac*self.G2
        if self.refine_panelRot:
            self.panelRot_dI_dtheta = SG*self.D.get_derivative_pixels(self._panelRot_id).as_numpy_array()
            if self.calc_curvatures:
                self.panelRot_d2I_dtheta2 = SG*self.D.get_second_derivative_pixels(self._panelRot_id).as_numpy_array()

    def _extract_panelXY_derivative_pixels(self):
        self.panelX_dI_dtheta = self.panelX_d2I_dtheta2 = 0
        self.panelY_dI_dtheta = self.panelY_d2I_dtheta2 = 0
        SG = self.scale_fac*self.G2
        if self.refine_panelXY:
            self.panelX_dI_dtheta = SG*self.D.get_derivative_pixels(self._panelX_id).as_numpy_array()
            self.panelY_dI_dtheta = SG*self.D.get_derivative_pixels(self._panelY_id).as_numpy_array()
        # TODO: curvatures

    def _extract_Fcell_derivative_pixels(self):
        self.fcell_deriv = self.fcell_second_deriv = 0
        if self.refine_Fcell:
            SG = self.scale_fac*self.G2
            self.fcell_deriv = SG*self.D.get_derivative_pixels(self._fcell_id).as_numpy_array()
            if self.calc_curvatures:
                self.fcell_second_deriv = SG*self.D.get_second_derivative_pixels(self._fcell_id).as_numpy_array()

    def _extract_pixel_data(self):
        self.model_bragg_spots = self.scale_fac*self.D.raw_pixels_roi.as_numpy_array()
        self._extract_Umatrix_derivative_pixels()
        self._extract_Bmatrix_derivative_pixels()
        self._extract_mosaic_parameter_m_derivative_pixels()
        self._extract_originZ_derivative_pixels()
        self._extract_Fcell_derivative_pixels()
        self._extract_spectra_coefficient_derivatives()
        self._extract_panelRot_derivative_pixels()
        self._extract_panelXY_derivative_pixels()

    def _update_ucell(self):
        if self.rescale_params:
            pars = self._get_ucell_vars(self._i_shot)
        else:
            _s = slice(self.ucell_xstart[self._i_shot], self.ucell_xstart[self._i_shot] + self.n_ucell_param, 1)
            pars = list(self.Xall[_s])
        self.UCELL_MAN[self._i_shot].variables = pars
        self._send_ucell_gradients_to_derivative_managers()
        self.D.Bmatrix = self.UCELL_MAN[self._i_shot].B_recipspace

    def _update_umatrix(self):
        self.D.Umatrix = self.CRYSTAL_MODELS[self._i_shot].get_U()

    def _update_beams(self):
        # sim_data instance has a nanoBragg beam object, which takes spectra and converts to nanoBragg xray_beams
        self.S.beam.spectra = self.SPECTRA[self._i_shot]
        self.D.xray_beams = self.S.beam.xray_beams

    def compute_functional_gradients_diag(self):
        self.compute_functional_and_gradients()
        return self._f, self._g, self.d

    #@profile
    def compute_functional_and_gradients(self):
        if self.calc_func:
            if self.verbose:
                self._print_iteration_header()

            self._MPI_save_state_of_refiner()

            if self.iteratively_freeze_parameters:
                if self.param_sels is None:
                    self.determine_parameter_freeze_order()

            # reset gradient and functional
            self.target_functional = 0
            self._update_Xall_from_x()

            self.grad = flex_double(self.n_total_params)
            if self.calc_curvatures:
                self.curv = flex_double(self.n_total_params)

            # current work has gain_fac at 1 (#TODO gain factor should effect the probability of observing the photons)
            self.gain_fac = self.Xall[self.gain_xpos]
            self.G2 = self.gain_fac ** 2

            self._update_Fcell()  # update the structure factor with the new x
            self._update_spectra_coefficients()  # updates the diffBragg lambda coefficients if refinining spectra

            if self.CRYSTAL_GT is not None:
                self._MPI_initialize_GT_crystal_misorientation_analysis()

            for self._i_shot in self.shot_ids:
                if self._i_shot in self.bad_shot_list:
                    continue
                self.scale_fac = self._get_spot_scale(self._i_shot)

                # TODO: Omatrix update? All crystal models here should have the same to_primitive operation, ideally
                self._update_beams()
                self._update_umatrix()
                self._update_ucell()
                self._update_ncells()
                self._update_rotXYZ()
                n_spots = len(self.NANOBRAGG_ROIS[self._i_shot])
                for i_spot in range(n_spots):
                    self._i_spot = i_spot

                    if self.selection_flags is not None:
                        if self._i_shot not in self.selection_flags:
                            continue
                        elif not self.selection_flags[self._i_shot][i_spot]:
                            continue

                    self._panel_id = int(self.PANEL_IDS[self._i_shot][i_spot])

                    if self.verbose and i_spot % self.spot_print_stride == 0:
                        print("diffBragg: img %d/%d; spot %d/%d; panel %d" \
                              % (self._i_shot + 1, self.n_shots, i_spot + 1, n_spots, self._panel_id)) #, flush=True)

                    self.Imeas = self.ROI_IMGS[self._i_shot][i_spot]
                    self._update_dxtbx_detector()
                    if i_spot == 0:
                        if self.refine_panelRot:
                            print("ROT ANGLE : %.4f" % self._get_panelRot_val(self._panel_id))

                        if self.refine_panelXY:
                            print("XY: %.4f %f" % self._get_panelXY_val(self._panel_id))
                    self._run_diffBragg_current(i_spot)
                    self._set_background_plane(i_spot)
                    self._extract_pixel_data()
                    self._evaluate_averageI()

                    # here we can correlate modelLambda with Imeas
                    self._increment_model_data_correlation()

                    if self.poisson_only:
                        self._evaluate_log_averageI()
                    else:
                        self._evaluate_log_averageI_plus_sigma_readout()

                    #self._max_h_sanity_test()
                    self._derivative_convenience_factors()

                    self.target_functional += self._target_accumulate()

                    # make any plots (this only matters if proper flags have been set)
                    self._show_plots(i_spot, n_spots)

                    # accumulate the per pixel derivatives
                    if self.bg_extracted:
                        self._bg_extracted_derivatives(i_spot)
                    else:
                        self._background_derivatives(i_spot)
                    self._Umatrix_derivatives()
                    self._Bmatrix_derivatives()
                    self._mosaic_parameter_m_derivatives()
                    self._originZ_derivatives()
                    self._panelRot_derivatives()
                    self._panelXY_derivatives()
                    self._spot_scale_derivatives()
                    self._gain_factor_derivatives()
                    self._Fcell_derivatives(i_spot)
                    self._spectra_derivatives()
                    # Done with derivative accumulation

            #    self.image_corr[self._i_shot] = self.image_corr[self._i_shot] / self.image_corr_norm[self._i_shot]

            self._MPI_aggregate_model_data_correlations()
            # TODO add in the priors:
            self._priors()
            self._parameter_freezes()
            self._mpi_aggregation()

            self._f = self.target_functional
            self._g = self.g_for_lbfgs
            self.g = self.g_for_lbfgs  # TODO why all these repeated definitions ?, self.g is needed by _verify_diag

            self._curvature_analysis()

            # reset ROI pixels TODO: is this necessary
            self.D.raw_pixels *= 0
            self.gnorm = norm(self.grad)

            if self.verbose:
                if self.CRYSTAL_GT is not None:
                    self._MPI_print_GT_crystal_misorientation_analysis()
                self._print_image_correlation_analysis()
                self.print_step()
                self.print_step_grads()

            self.iterations += 1
            self.f_vals.append(self.target_functional)
            time.sleep(self.pause_after_iteration)

            if self.calc_curvatures and not self.use_curvatures:
                if self.num_positive_curvatures == self.use_curvatures_threshold:
                    raise BreakToUseCurvatures

        return self._f, self._g

    def _increment_model_data_correlation(self):
        if self.image_corr[self._i_shot] is None:
            self.image_corr[self._i_shot] = 0
            self.image_corr_norm[self._i_shot] = 0
        if self.compute_image_model_correlation:
            _overlay_corr, _ = pearsonr(self.Imeas.ravel(), self.model_Lambda.ravel())
        else:
            _overlay_corr = NAN
        self.image_corr[self._i_shot] += _overlay_corr
        self.image_corr_norm[self._i_shot] += 1

    def _background_derivatives(self, i_spot):
        if self.refine_background_planes:
            if self.bg_offset_only:  # option to only refine c (t3 in manuscript) plane
                abc_dI_dtheta = [0, 0, self.G2*self.c]
                abc_d2I_dtheta2 = [0, 0, 0]
            else:
                xr = self.XREL[self._i_shot][i_spot]  # fast scan pixels
                yr = self.YREL[self._i_shot][i_spot]  # slow scan pixels
                if self.G2 != 1:
                    abc_dI_dtheta = [xr*self.G2, yr*self.G2, self.G2]
                else:
                    abc_dI_dtheta = [xr, yr, self.G2]
                abc_d2I_dtheta2 = [0, 0, 0]

            if self.rescale_params or self.bg_offset_positive:
                if self.bg_offset_only:
                    # here we apply case2 type reparameterization to the c derivative
                    abc_dI_dx = [0, 0, abc_dI_dtheta[2]*self.c*self.c_sigma]
                    abc_d2I_dx2 = [0, 0, abc_dI_dx[2]*self.c_sigma]
                else:
                    # here we apply case1 type reparameterization to a,b,c derivs
                    abc_dI_dx = [abc_dI_dtheta[0]*self.a_sigma,
                                 abc_dI_dtheta[1]*self.b_sigma,
                                 abc_dI_dtheta[2]*self.c_sigma]
                    abc_d2I_dx2 = [0, 0, 0]
                bg_deriv = abc_dI_dx
                bg_second_deriv = abc_d2I_dx2
            else:
                bg_deriv = abc_dI_dtheta
                bg_second_deriv = abc_d2I_dtheta2

            x_positions = [self.bg_a_xstart[self._i_shot][i_spot],
                           self.bg_b_xstart[self._i_shot][i_spot],
                           self.bg_c_xstart[self._i_shot][i_spot]]
            for ii, xpos in enumerate(x_positions):
                d = bg_deriv[ii]
                self.grad[xpos] += self._grad_accumulate(d)
                if self.calc_curvatures:
                    d2 = bg_second_deriv[ii]
                    self.curv[xpos] += self._curv_accumulate(d, d2)

    def _get_rotXYZ_first_derivs(self):
        if self.rescale_params:
            # rot XYZ uses a case1 type rescaling
            derivs = [self.rotX_sigma*self.rotX_dI_dtheta,
                      self.rotY_sigma*self.rotY_dI_dtheta,
                      self.rotZ_sigma*self.rotZ_dI_dtheta]
        else:
            derivs = [self.rotX_dI_dtheta, self.rotY_dI_dtheta, self.rotZ_dI_dtheta]

        return derivs

    def _get_rotXYZ_second_derivs(self):
        if self.rescale_params:
            # rot XYZ uses a case1 type rescaling
            second_derivs = [(self.rotX_sigma**2)*self.rotX_d2I_dtheta2,
                             (self.rotY_sigma**2)*self.rotY_d2I_dtheta2,
                             (self.rotZ_sigma**2)*self.rotZ_d2I_dtheta2]
        else:
            second_derivs = [self.rotX_d2I_dtheta2, self.rotY_d2I_dtheta2, self.rotZ_d2I_dtheta2]

        return second_derivs

    def _get_spectra_first_derivs(self):
        if self.refine_lambda0 or self.refine_lambda1:
            assert self.rescale_params
            derivs = []
            for i_coef in range(self.n_spectra_param):
                dI_dtheta = self.spectra_derivs[i_coef]

                # TODO make this part of a `parameter class`, so other parameters can borrow same code when using bounds
                init = self.spectra_coefficients_init[i_coef]
                sigma = self.spectra_coefficients_sigma[i_coef]
                x = self.Xall[self.spectra_coef_xstart + i_coef]
                low, high = self.lambda_coef_ranges[i_coef]
                rng = high - low
                cos_arg = sigma * (x-1) + ASIN(2*(init-low)/rng - 1)
                dtheta_dx = rng/2 * COS(cos_arg) * sigma
                d = dI_dtheta * dtheta_dx
                derivs.append(d)
                #derivs.append(dI_dtheta * sigma)
            return derivs

    def _spectra_derivatives(self):
        if self.refine_lambda0 or self.refine_lambda1:
            derivs = self._get_spectra_first_derivs()
            xstart = self.spectra_coef_xstart
            for i_coef in range(self.n_spectra_param):
                if not self.is_being_refined[xstart+i_coef]:
                    continue
                d = derivs[i_coef]
                self.grad[xstart + i_coef] += self._grad_accumulate(d)
                if self.calc_curvatures:
                    raise NotImplementedError

    def _Umatrix_derivatives(self):
        if self.refine_Umatrix:
            x_positions = [self.rotX_xpos[self._i_shot],
                           self.rotY_xpos[self._i_shot],
                           self.rotZ_xpos[self._i_shot]]
            derivs = self._get_rotXYZ_first_derivs()
            second_derivs = self._get_rotXYZ_second_derivs()
            for ii, xpos in enumerate(x_positions):
                d = derivs[ii]
                self.grad[xpos] += self._grad_accumulate(d)
                if self.calc_curvatures:
                    d2 = second_derivs[ii]
                    self.curv[xpos] += self._curv_accumulate(d, d2)

    def _get_ucell_first_derivatives(self):
        derivs = []
        for i_ucell in range(self.n_ucell_param):
            d = self.ucell_dI_dtheta[i_ucell]
            if self.rescale_params:
                sigma = self.ucell_sigmas[i_ucell]
                d = d*sigma
            derivs.append(d)
        return derivs

    def _get_ucell_second_derivatives(self):
        second_derivs = []
        for i_ucell in range(self.n_ucell_param):
            d2 = self.ucell_d2I_dtheta2[i_ucell]
            if self.rescale_params:
                sigma_squared = self.ucell_sigmas[i_ucell]**2
                d2 = d2*sigma_squared
            second_derivs.append(d2)
        return second_derivs

    def _Bmatrix_derivatives(self):
        if self.refine_Bmatrix:
            # unit cell derivative
            derivs = self._get_ucell_first_derivatives()
            second_derivs = self._get_ucell_second_derivatives()
            for i_ucell in range(self.n_ucell_param):
                xpos = self.ucell_xstart[self._i_shot] + i_ucell
                d = derivs[i_ucell]
                self.grad[xpos] += self._grad_accumulate(d)
                if self.calc_curvatures:
                    d2 = second_derivs[i_ucell]
                    self.curv[xpos] += self._curv_accumulate(d, d2)

    def _mosaic_parameter_m_derivatives(self):
        if self.refine_ncells:
            thetas = self._get_m_val(self._i_shot)  # mosaic parameters "m"
            for i_ncell in range(self.n_ncells_param):
                theta_minus_three = thetas[i_ncell] - 3
                sig = self.m_sigma
                if self.rescale_params:
                    # case 3 rescaling
                    sig_theta_minus_three = sig*theta_minus_three
                    d = self.m_dI_dtheta[i_ncell]*sig_theta_minus_three
                    d2 = self.m_d2I_dtheta2[i_ncell]*(sig_theta_minus_three*sig_theta_minus_three) + \
                         self.m_dI_dtheta[i_ncell]*(sig*sig_theta_minus_three)
                else:
                    # case 4 rescaling with theta_o = 3
                    d = self.m_dI_dtheta[i_ncell]*theta_minus_three
                    d2 = self.m_d2I_dtheta2[i_ncell]*(theta_minus_three*theta_minus_three) + self.m_dI_dtheta[i_ncell]*theta_minus_three

                xpos = self.ncells_xstart[self._i_shot] + i_ncell
                self.grad[xpos] += self._grad_accumulate(d)
                if self.calc_curvatures:
                    self.curv[xpos] += self._curv_accumulate(d, d2)

    def _panelRot_derivatives(self):
        if self.refine_panelRot:
            d = self.panelRot_dI_dtheta*self.panelRot_sigma
            d2 = self.panelRot_d2I_dtheta2*(self.panelRot_sigma*self.panelRot_sigma)

            xpos = self.panelRot_xstart + self.panel_group_from_id[self._panel_id]

            self.grad[xpos] += self._grad_accumulate(d)
            if self.calc_curvatures:
                self.curv[xpos] += self._curv_accumulate(d, d2)

    def _panelXY_derivatives(self):
        if self.refine_panelXY:
            d_X = self.panelX_dI_dtheta*self.panelX_sigma
            d_Y = self.panelY_dI_dtheta*self.panelY_sigma
            #d2_X = d2_Y = 0 #TODO: curvatires

            xpos_X = self.panelXY_xstart + 2*self.panel_group_from_id[self._panel_id]
            xpos_Y = xpos_X + 1

            self.grad[xpos_X] += self._grad_accumulate(d_X)
            self.grad[xpos_Y] += self._grad_accumulate(d_Y)

    def _originZ_derivatives(self):
        if self.refine_detdist:
            if self.rescale_params:
                if self.originZ_range is not None:
                    init = self.shot_originZ_init[self._i_shot]
                    sigma = self.originZ_sigma
                    x = self.Xall[self.originZ_xpos[self._i_shot]]
                    low, high = self.originZ_range
                    rng = high - low
                    cos_arg = sigma * (x - 1) + ASIN(2 * (init - low) / rng - 1)
                    dtheta_dx = rng / 2 * COS(cos_arg) * sigma
                    d = self.detdist_dI_dtheta * dtheta_dx
                    d2 = 0  #TODO implement..

                else:
                    #NOTE old way:
                    # case 1 type of rescaling
                    d = self.detdist_dI_dtheta*self.originZ_sigma
                    d2 = self.detdist_d2I_dtheta2*(self.originZ_sigma*self.originZ_sigma)
            else:
                d = 1*self.detdist_dI_dtheta
                d2 = 1*self.detdist_d2I_dtheta2

            xpos = self.originZ_xpos[self._i_shot]
            self.grad[xpos] += self._grad_accumulate(d)
            if self.calc_curvatures:
                if self.originZ_range is not None and self.rescale_params:
                    raise NotImplementedError("You Cannot.")
                self.curv[xpos] += self._curv_accumulate(d, d2)

    def _Fcell_derivatives(self, i_spot):
        # asu index
        miller_idx = self.ASU[self._i_shot][i_spot]
        # get multiplicity of this index
        multi = self.hkl_frequency[self.idx_from_asu[miller_idx]]
        # check if we are freezing this index during refinement
        freeze_this_hkl = False
        if self.freeze_idx is not None:
            freeze_this_hkl = self.freeze_idx[miller_idx]
        # do the derivative
        if self.refine_Fcell and multi >= self.min_multiplicity and not freeze_this_hkl:
            i_fcell = self.idx_from_asu[self.ASU[self._i_shot][i_spot]]
            xpos = self.fcell_xstart + i_fcell

            self.fcell_dI_dtheta = self.fcell_deriv
            self.fcell_d2I_d2theta2 = self.fcell_second_deriv

            if self.rescale_params:
                fcell = self._get_fcell_val(i_fcell)  # todo: interact with a vectorized object instead
                resolution_id = self.res_group_id_from_fcell_index[i_fcell]
                sig = self.sigma_for_res_id[resolution_id] * self.fcell_sigma_scale
                if self.log_fcells:
                    # case 2 rescaling
                    sig_times_fcell = sig*fcell
                    d = sig_times_fcell*self.fcell_dI_dtheta
                    d2 = (sig_times_fcell*sig_times_fcell)*self.fcell_d2I_d2theta2 + (sig*sig_times_fcell)*self.fcell_dI_dtheta
                else:
                    # case 1 rescaling
                    d = sig*self.fcell_dI_dtheta
                    d2 = (sig*sig)*self.fcell_d2I_d2theta2
            else:
                d = self.fcell_dI_dtheta
                d2 = self.fcell_d2I_d2theta2

            self.grad[xpos] += self._grad_accumulate(d)
            if self.calc_curvatures:
                self.curv[xpos] += self._curv_accumulate(d, d2)

    def _bg_extracted_derivatives(self, return_derivatives=False):
        if self.refine_background_planes:
            assert self.rescale_params
            dI_dtheta = self.G2 * self.tilt_plane
            sig = self.bg_coef_sigma
            # case 2 type rescaling
            d = dI_dtheta*self.bg_coef * sig
            d2 = dI_dtheta*(self.bg_coef*sig*sig)

            xpos = self.bg_coef_xpos[self._i_shot]
            self.grad[xpos] += self._grad_accumulate(d)
            if self.calc_curvatures:
                self.curv[xpos] += self._curv_accumulate(d, d2)
            if return_derivatives:
                return d, d2

    def _spot_scale_derivatives(self, return_derivatives=False):
        if self.refine_crystal_scale:
            dI_dtheta = (self.G2/self.scale_fac)*self.model_bragg_spots
            # second derivative is 0 with respect to scale factor
            if self.rescale_params:
                sig = self.spot_scale_sigma
                # case 2 type rescaling
                d = dI_dtheta*self.scale_fac * sig
                d2 = dI_dtheta*(self.scale_fac*sig*sig)
            else:
                # case 4 type rescaling
                d = dI_dtheta*self.scale_fac
                d2 = d  # same as first derivative

            xpos = self.spot_scale_xpos[self._i_shot]
            self.grad[xpos] += self._grad_accumulate(d)
            if self.calc_curvatures:
                self.curv[xpos] += self._curv_accumulate(d, d2)
        if return_derivatives:
            return d, d2

    def _gain_factor_derivatives(self):
        if self.refine_gain_fac:
            raise NotImplementedError("gain factor derivatives need more testing")
            d = 2*self.gain_fac*(self.tilt_plane + self.model_bragg_spots)
            self.grad[self.gain_xpos] += self._grad_accumulate(d)
            if self.calc_curvatures:
                d2 = d / self.gain_fac
                self.curv[self.gain_xpos] += self._curv_accumulate(d, d2)

    def _max_h_sanity_test(self, i_spot):
        max_h = tuple(map(int, self.D.max_I_hkl))
        refinement_h = self.ASU[self._i_shot][i_spot]
        equivs = [i.h() for i in miller.sym_equiv_indices(self.space_group, refinement_h).indices()]
        if not max_h in equivs and self.debug:  # TODO understand this more, how does this effect things
            print("Warning max_h  mismatch!!!!!!")

    def _priors(self):
        # experimental, not yet proven to help
        if self.use_ucell_priors and self.refine_Bmatrix:
            for ii in range(self.n_shots):
                for jj in range(self.n_ucell_param):
                    xpos = self.ucell_xstart[ii] + jj
                    ucell_p = self.Xall[xpos]
                    sig_square = self.sig_ucell[jj] ** 2
                    self.target_functional += (ucell_p - self.ave_ucell[jj]) ** 2 / 2 / sig_square
                    self.grad[xpos] += (ucell_p - self.ave_ucell[jj]) / sig_square
                    if self.calc_curvatures:
                        self.curv[xpos] += 1 / sig_square

        if self.use_rot_priors and self.refine_Umatrix:
            for ii in range(self.n_shots):
                x_positions = [self.rotX_xpos[self._i_shot],
                               self.rotY_xpos[self._i_shot],
                               self.rotZ_xpos[self._i_shot]]
                for xpos in x_positions:
                    rot_p = self.Xall[xpos]
                    sig_square = self.sig_rot ** 2
                    self.target_functional += rot_p ** 2 / 2 / sig_square
                    self.grad[xpos] += rot_p / sig_square
                    if self.calc_curvatures:
                        self.curv[xpos] += 1 / sig_square

    def _parameter_freezes(self):
        if self.iteratively_freeze_parameters and self.iterations % self.number_of_frozen_iterations == 0:
            print("\n\n\t\tSwitching!!\n\n")
            freeze_sel = next(self.param_sels)
            self.grad.set_selected(freeze_sel, 0)
            if self.calc_curvatures:
                self.curv.set_selected(freeze_sel, 0)

    def _mpi_aggregation(self):
        # reduce the broadcast summed results:
        if self.I_AM_ROOT:
            print("\nMPI reduce on functionals and gradients...")
        self.target_functional = self._MPI_reduce_broadcast(self.target_functional)
        self.grad = self._MPI_reduce_broadcast(self.grad)
        self.rotx, self.roty, self.rotz, self.uc_vals, self.ncells_vals, self.scale_vals, \
        self.scale_vals_truths, self.origZ_vals = self._unpack_internal(self.Xall, lst_is_x=True)
        self.Grotx, self.Groty, self.Grotz, self.Guc_vals, self.Gncells_vals, self.Gscale_vals, _, self.GorigZ_vals = \
            self._unpack_internal(self.grad, lst_is_x=False)
        if self.calc_curvatures:
            self.curv = self._MPI_reduce_broadcast(self.curv)
            self.CUrotx, self.CUroty, self.CUrotz, self.CUuc_vals, self.CUncells_vals, self.CUscale_vals, _, self.CUorigZ_vals = \
                self._unpack_internal(self.curv, lst_is_x=False)
        self.tot_fcell_kludge = self._MPI_reduce_broadcast(self.num_Fcell_kludge)

    def _curvature_analysis(self):
        self.tot_neg_curv = 0
        self.neg_curv_shots = []
        if self.calc_curvatures:
            self.is_negative_curvature = self.curv.as_numpy_array() < 0
            self.tot_neg_curv = sum(self.is_negative_curvature)

        if self.calc_curvatures and not self.use_curvatures:
            if self.tot_neg_curv == 0:
                self.num_positive_curvatures += 1
                self.d = self.d_for_lbfgs #flex_double(self.curv.as_numpy_array())
                self._verify_diag()
            else:
                self.num_positive_curvatures = 0
                self.d = None

        if self.use_curvatures:
            if self.tot_neg_curv == 0:
                self.request_diag_once = False
                self.diag_mode = "always"  # TODO is this proper place to set ?
                self.d = self.d_for_lbfgs #flex_double(self.curv.as_numpy_array())
                self._verify_diag()
            elif self.fix_params_with_negative_curvature:
                self.request_diag_once = False
                self.diag_mode = "always"
                is_ref = self.is_being_refined.as_numpy_array()
                is_ref[self.is_negative_curvature] = False
                self.is_being_refined = FLEX_BOOL(is_ref)
                # set the BFGS parameter array
                self.x = self.x_for_lbfgs
                assert( self.n == len(self.x))
                # make the mapping from x to Xall
                refine_pos = WHERE(self.is_being_refined.as_numpy_array())[0]
                self.x2xall = {xi: xalli for xi, xalli in enumerate(refine_pos)}
                self.xall2x = {xalli: xi for xi, xalli in enumerate(refine_pos)}
                self.g = self.g_for_lbfgs
                self.d = self.d_for_lbfgs
                self._g = self.g_for_lbfgs
                self._verify_diag()
                print("Breaking to freeze %d curvatures" % self.tot_neg_curv)
                raise BreakToUseCurvatures
            else:
                if self.debug:
                    print("\n\t******************************************")
                    print("\tFREEZING THE CURVATURE: DISASTER AVERSION")
                    print("*\t*****************************************")
        else:
            self.d = None

    def _MPI_initialize_GT_crystal_misorientation_analysis(self):
        self.all_ang_off = []
        self.current_ang_off = []
        for i in range(self.n_shots):
            try:
                Ctru = self.CRYSTAL_GT[i]
                atru, btru, ctru = Ctru.get_real_space_vectors()
                ang, ax = self.get_correction_misset(as_axis_angle_deg=True, i_shot=i)
                B = self.get_refined_Bmatrix(i)
                C = deepcopy(self.CRYSTAL_MODELS[i])
                C.set_B(B)
                if ang > 0:
                    C.rotate_around_origin(ax, ang)
                ang_off = compare_with_ground_truth(atru, btru, ctru,
                                                    [C],
                                                    symbol=self.symbol)[0]
            except Exception:
                ang_off = -1
            if self.filter_bad_shots and self.iterations == 0:
                if ang_off == -1 or ang_off > 0.015:
                    self.bad_shot_list.append(i)

            self.current_ang_off.append(ang_off)
            self.all_ang_off.append(ang_off)

        if self.init_ang_off is None:
            self.init_ang_off = deepcopy(self.current_ang_off)

        self.bad_shot_list = list(set(self.bad_shot_list))

        self.all_ang_off = self._init_gather_ang_off()
        self.n_bad_shots = self._init_n_bad_shots()



    def get_init_misorientation(self, i_shot):
        ang = NAN
        if self.CRYSTAL_GT is not None:
            ang = self.init_ang_off[i_shot]
        return ang

    def get_current_misorientation(self, i_shot):
        ang = NAN
        if self.CRYSTAL_GT is not None:
            ang = self.current_ang_off[i_shot]
        return ang

    def _MPI_print_GT_crystal_misorientation_analysis(self):
        all_ang_off = self._get_ang_off()
        n_broken_misset = sum([1 for aa in all_ang_off if aa == -1])
        n_bad_misset = sum([1 for aa in all_ang_off if aa > 0.1])
        n_misset = len(all_ang_off)
        _pos_misset_vals = [aa for aa in all_ang_off if aa > 0]
        misset_median = median(_pos_misset_vals)
        misset_mean = mean(_pos_misset_vals)
        misset_max = -1
        misset_min = -1
        if _pos_misset_vals:
            misset_max = max(_pos_misset_vals)
            misset_min = min(_pos_misset_vals)
        if self.refine_Umatrix or self.refine_Bmatrix and self.print_all_missets:
            print("\nMissets\n========")
            all_ang_off_s = ["%.5f" % aa for aa in all_ang_off]
            print(", ".join(all_ang_off_s))
            print("N shots deemed bad from missets: %d" % self.n_bad_shots)
        print("MISSETTING median: %.4f; mean: %.4f, max: %.4f, min %.4f, num > .1 deg: %d/%d; num broken=%d"
              % (misset_median, misset_mean, misset_max, misset_min, n_bad_misset, n_misset, n_broken_misset))
        self.all_ang_off = all_ang_off

    def _get_image_correlation(self, i_shot):
        corr = NAN
        if self.image_corr[i_shot] is not None:
            corr = self.image_corr[i_shot] / self.image_corr_norm[i_shot]
        return corr

    def _get_init_image_correlation(self, i_shot):
        corr = NAN
        if self.image_corr[i_shot] is not None:
            corr = self.init_image_corr[i_shot]
        return corr

    def _print_image_correlation_analysis(self):
        all_corr_str = ["%.2f" % ic for ic in self.all_image_corr]
        print("Correlation stats:")
        if self.print_all_corr:
            print(", ".join(all_corr_str))
            print("---------------")
        n_bad_corr = sum([1 for ic in self.all_image_corr if ic < 0.25])
        print("CORRELATION median: %.4f; mean: %.4f, max: %.4f, min %.4f, num <.25: %d/%d;"
              % (median(self.all_image_corr), mean(self.all_image_corr), max(self.all_image_corr),
                 min(self.all_image_corr), n_bad_corr, len(self.all_image_corr)))

    def _get_refinement_string_label(self):
        refine_str = "refining "
        if self.refine_Fcell:
            refine_str += "fcell, "
        if self.refine_ncells:
            refine_str += "Ncells, "
        if self.refine_Bmatrix:
            refine_str += "Bmat, "
        if self.refine_Umatrix:
            refine_str += "Umat, "
        if self.refine_crystal_scale:
            refine_str += "scale, "
        if self.refine_background_planes:
            refine_str += "bkgrnd, "
        if self.refine_detdist:
            refine_str += "originZ, "
        if self.refine_panelRot:
            refine_str += "panelRot, "
        if self.refine_panelXY:
            refine_str += "panelXY, "
        return refine_str

    def _print_iteration_header(self):
        refine_str = self._get_refinement_string_label()
        border = "<><><><><><><><><><><><><><><><>"
        if self.use_curvatures:

            print(
                "%s%s%s%s\nTrial%d (%s): Compute functional and gradients Iter %d %s(Using Curvatures)%s\n%s%s%s%s"
                % (Bcolors.HEADER, border,border,border, self.trial_id + 1, refine_str, self.iterations + 1, Bcolors.OKGREEN, Bcolors.HEADER, border,border,border, Bcolors.ENDC))
        else:
            print("%s%s%s%s\n, Trial%d (%s): Compute functional and gradients Iter %d PosCurva %d\n%s%s%s%s"
                  % (Bcolors.HEADER, border, border, border, self.trial_id + 1, refine_str, self.iterations + 1, self.num_positive_curvatures, border, border,border, Bcolors.ENDC))

    def _MPI_save_state_of_refiner(self):
        if self.I_AM_ROOT and self.output_dir is not None:
            outf = os.path.join(self.output_dir, "_fcell_trial%d_iter%d" % (self.trial_id, self.iterations))
            if self.rescale_params:
                fvals = [self._get_fcell_val(i_fcell) for i_fcell in range(self.n_global_fcell)]
                fvals = ARRAY(fvals)
            else:
                fvals = self.Xall[self.fcell_xstart:self.fcell_xstart + self.n_global_fcell].as_numpy_array()
            SAVEZ(outf, fvals=fvals, x=self.Xall.as_numpy_array())

    def _show_plots(self, i_spot, n_spots):
        if self.I_AM_ROOT and self.plot_images and self.iterations % self.plot_stride == 0 and self._i_shot == self.index_of_displayed_image:
            if i_spot % self.plot_spot_stride == 0:
                xr = self.XREL[self._i_shot][i_spot]  # fast scan pixels
                yr = self.YREL[self._i_shot][i_spot]  # slow scan pixels
                if self.plot_residuals:
                    self.ax.clear()
                    residual = self.model_Lambda - self.Imeas
                    x = residual.max()
                    #else:
                    #    x = mean([x, residual.max()])
                    self.ax.plot_surface(xr, yr, residual, rstride=2, cstride=2, alpha=0.3, cmap='coolwarm')
                    self.ax.contour(xr, yr, residual, zdir='z', offset=-x, cmap='coolwarm')
                    self.ax.set_yticks(range(yr.min(), yr.max()))
                    self.ax.set_xticks(range(xr.min(), xr.max()))
                    self.ax.set_xticklabels([])
                    self.ax.set_yticklabels([])
                    self.ax.set_zlim(-x, x)
                    self.ax.set_title("residual (photons)")
                else:
                    m = self.Imeas[self.Imeas > 1e-9].mean()
                    s = self.Imeas[self.Imeas > 1e-9].std()
                    vmax = m + 5 * s
                    vmin = m - s
                    m2 = self.model_Lambda.mean()
                    s2 = self.model_Lambda.std()
                    self.ax1.images[0].set_data(self.model_Lambda)
                    self.ax1.images[0].set_clim(vmin, vmax)
                    self.ax2.images[0].set_data(self.Imeas)
                    self.ax2.images[0].set_clim(vmin, vmax)
                plt.suptitle("Iterations = %d, image %d / %d"
                             % (self.iterations, i_spot + 1, n_spots))
                self.fig.canvas.draw()
                plt.pause(.02)

    def _poisson_target(self):
        fterm = (self.model_Lambda - self.Imeas * self.log_Lambda).sum()
        return fterm

    def _poisson_d(self, d):
        gterm = (d * self.one_minus_k_over_Lambda).sum()
        return gterm

    def _poisson_d2(self, d, d2):
        cterm = d2 * self.one_minus_k_over_Lambda + d * d * self.k_over_squared_Lambda
        return cterm.sum()

    def _gaussian_target(self):
        fterm = .5*(self.log2pi + self.log_v + self.u*self.u*self.one_over_v).sum()
        return fterm
        #fterm = (self.log2pi + 2*self.log_Lambda_plus_sigma_readout + self.u_u_one_over_v).sum()
        #fterm = (self.log_Lambda_plus_sigma_readout + .5*self.u_u_one_over_v).sum()
        #return fterm

    def _gaussian_d(self, d):
        #gterm = (d*self.one_over_v_times_one_minus_2u_minus_u_squared_over_v).sum()
        gterm = .5 * (d * self.one_over_v * self.one_minus_2u_minus_u_squared_over_v).sum()
        #a = self.one_over_v_times_one_minus_2u_minus_u_squared_over_v
        #gterm = numexpr.evaluate('sum(d*a)')
        #local_dict={'a': self.one_over_v_times_one_minus_2u_minus_u_squared_over_v, 'd':d})
        #gterm = 0.5*gterm[()]
        return gterm

    def _gaussian_d2(self, d, d2):
        #cterm = self.one_over_v * (d2*self.one_minus_2u_minus_u_squared_over_v -
        #                           d*d*(self.one_over_v*self.one_minus_2u_minus_u_squared_over_v -
        #                                    (2 + 2*self.u*self.one_over_v + self.u*self.u*self.one_over_v*self.one_over_v)))
        #cterm = .5 * (cterm.sum())
        cterm = self.one_over_v * (d2*self.one_minus_2u_minus_u_squared_over_v -
                                   d*d*(self.one_over_v_times_one_minus_2u_minus_u_squared_over_v -
                                        (2 + 2*self.u_times_one_over_v + self.u_u_one_over_v*self.one_over_v)))
        cterm = .5 * (cterm.sum())
        return cterm

    def _derivative_convenience_factors(self):
        one_over_Lambda = 1. / self.model_Lambda
        self.one_minus_k_over_Lambda = (1. - self.Imeas * one_over_Lambda)
        self.k_over_squared_Lambda = self.Imeas * one_over_Lambda * one_over_Lambda

        self.u = self.Imeas - self.model_Lambda
        self.one_over_v = 1. / (self.model_Lambda + self.sigma_r ** 2)
        self.one_minus_2u_minus_u_squared_over_v = 1 - 2 * self.u - self.u * self.u * self.one_over_v
        self.u_times_one_over_v = self.u*self.one_over_v
        self.u_u_one_over_v = self.u*self.u_times_one_over_v
        #self.one_minus_2u_minus_u_squared_over_v = 1 - 2 * self.u - self.u_u_one_over_v
        self.one_over_v_times_one_minus_2u_minus_u_squared_over_v = self.one_over_v*self.one_minus_2u_minus_u_squared_over_v

    def _evaluate_log_averageI(self):  # for Poisson only stats
        # fix log(x<=0)
        try:
            self.log_Lambda = np_log(self.model_Lambda)
        except FloatingPointError:
            pass
        if any((self.model_Lambda <= 0).ravel()):
            self.num_kludge += 1
            is_bad = self.model_Lambda <= 0
            self.log_Lambda[is_bad] = 1e-6
            print("\n<><><><><><><><>\n\tWARNING: NEGATIVE INTENSITY IN MODEL (kludges=%d)!!!!!!!!!\n<><><><><><><><><>\n" % self.num_kludge)
        #    raise ValueError("model of Bragg spots cannot have negative intensities...")
        self.log_Lambda[self.model_Lambda <= 0] = 0

    def _evaluate_log_averageI_plus_sigma_readout(self):
        v = self.model_Lambda + self.sigma_r ** 2
        v_is_neg = (v <= 0).ravel()
        if any(v_is_neg):
            self.num_kludge += 1
            print("\n<><><><><><><><>\n\tWARNING: NEGATIVE INTENSITY IN MODEL!!!!!!!!!\n<><><><><><><><><>\n")
        #    raise ValueError("model of Bragg spots cannot have negative intensities...")
        self.log_v = np_log(v)
        self.log_v[v <= 0] = 0  # but will I ever kludge ?

    def print_step(self):
        """Deprecated"""
        names = self.UCELL_MAN[self._i_shot].variable_names
        vals = self.UCELL_MAN[self._i_shot].variables
        ucell_labels = []
        for n, v in zip(names, vals):
            ucell_labels.append('%s=%+2.7g' % (n, v))
        rotX = self._get_rotX(self._i_shot) #self.rot_scale*self.Xall[self.rotX_xpos[self._i_shot]]
        rotY = self._get_rotY(self._i_shot) #self.rot_scale*self.Xall[self.rotY_xpos[self._i_shot]]
        rotZ = self._get_rotZ(self._i_shot)  #self.rot_scale*self.Xall[self.rotZ_xpos[self._i_shot]]
        rot_labels = ["rotX=%+3.7g" % rotX, "rotY=%+3.7g" % rotY, "rotZ=%+3.4g" % rotZ]

        if self.refine_Umatrix or self.refine_Bmatrix or self.refine_crystal_scale or self.refine_ncells:
            if self.big_dump and HAS_PANDAS:
                master_data = {"Ncells": self.ncells_vals,
                               "scale": self.scale_vals,
                               "rotx": self.rotx,
                               "roty": self.roty,
                               "rotz": self.rotz, "origZ": self.origZ_vals}
                for i_uc in range(self.n_ucell_param):
                    master_data["uc%d" % i_uc] = self.uc_vals[i_uc]


                master_data = pandas.DataFrame(master_data)
                master_data["gain"] = self.Xall[self.gain_xpos]
                print(master_data.to_string(float_format="%2.7g"))

    def print_step_grads(self):
        names = self.UCELL_MAN[self._i_shot].variable_names
        vals = self.UCELL_MAN[self._i_shot].variables
        ucell_labels = []
        for i, (n, v) in enumerate(zip(names, vals)):
            grad = self.grad[self.ucell_xstart[self._i_shot] + i]
            ucell_labels.append('G%s=%+2.7g' % (n, grad))

        if self.big_dump and HAS_PANDAS:
            master_data ={"GNcells": self.Gncells_vals,
                          "Gscale": self.Gscale_vals,
                          "Grotx": self.Grotx,
                          "Groty": self.Groty,
                          "Grotz": self.Grotz, "GorigZ": self.GorigZ_vals}
            for i_uc in range(self.n_ucell_param):
                master_data["Guc%d" %i_uc]= self.Guc_vals[i_uc]
            master_data = pandas.DataFrame(master_data)
            master_data["Ggain"] = self.grad[self.gain_xpos]
            print(master_data.to_string(float_format="%2.7g"))

        if self.calc_curvatures:
            if self.big_dump and HAS_PANDAS:
                if self.refine_Umatrix or self.refine_Bmatrix or self.refine_crystal_scale or self.refine_ncells:
                    master_data = {"CUNcells": self.CUncells_vals,
                                   "CUscale": self.CUscale_vals,
                                   "CUrotx": self.CUrotx,
                                   "CUroty": self.CUroty,
                                   "CUrotz": self.CUrotz, "CUorigZ": self.CUorigZ_vals}

                    for i_uc in range(self.n_ucell_param):
                        master_data["CUuc%d" % i_uc] = self.CUuc_vals[i_uc]

                    master_data = pandas.DataFrame(master_data)
                    master_data["CUgain"] = self.curv[self.gain_xpos]
                    print(master_data.to_string(float_format="%2.7g"))

        # Compute the mean, min, max, variance  and median crystal scale
        # Note we must also include the spot_scale in the diffBragg instance if its not unity
        _sv = [self.D.spot_scale*s for s in self.scale_vals]
        stats = (median(_sv),
                 mean(_sv),
                 min(_sv),
                 max(_sv),
                 std(_sv))
        scale_stat_names =["median", "mean", "min", "max", "sigma"]
        scale_stats = ["%s=%.4f" % name_stat for name_stat in zip(scale_stat_names, stats)]
        scale_stats_string = "SCALE FACTOR STATS: " + ", ".join(scale_stats)
        if self.scale_vals_truths is not None:
            scale_resid = [ABS(s-stru) for s, stru in zip(_sv, self.scale_vals_truths)]
            scale_stats_string += ", truth_resid=%.4f" % median(scale_resid)

        # TODO : use a median for a vals if refining Ncells per shot or unit cell per shot
        scale_stats_string += ", Ncells=%.3f" % self.ncells_vals[0]
        uc_string = ", "
        ucparam_names = self.UCELL_MAN[0].variable_names
        for i_ucparam, ucparam_lst in enumerate(self.uc_vals):
            param_val = median(ucparam_lst)
            uc_string += "%s=%.3f, " % (ucparam_names[i_ucparam], param_val)
        scale_stats_string += uc_string
        scale_stats_string += "originZ=%f, " % median(self.origZ_vals)

        Xnorm = norm(self.x)  # NOTEX
        R1 = -1
        R1_i = -1
        self.R_overall = -1
        ncurv = 0
        if self.calc_curvatures:
            ncurv = len(self.curv > 0)


        if self.Fref is not None and self.iterations % self.merge_stat_frequency == 0:
            self.R_overall = self.Fobs_Fref_Rfactor(use_binning=False, auto_scale=self.scale_r1)
            self.CC_overall = self.Fobs.correlation(self.Fref_aligned).coefficient()
            print("R-factor overall: %.4f, CC overall: %.4f" % (self.R_overall, self.CC_overall))
            if self.print_resolution_bins:
                print("R-factor (shells):")
                print(self.Fobs_Fref_Rfactor(use_binning=True, auto_scale=self.scale_r1).show())
                print("CC (shells):")
                self.Fobs.correlation(self.Fref_aligned, use_binning=True).show()

        print(
            "%s\n\t%s, F=%2.7g, |G|=%2.7g, eps*|X|=%2.7g,%s R1=%2.7g (R1 at start=%2.7g), Fcell kludges=%d, Neg. Curv.: %d/%d on shots=%s\n"
            % (scale_stats_string, Bcolors.OKBLUE, self._f, self.gnorm, Xnorm * self.trad_conv_eps, Bcolors.ENDC, self.R_overall, self.init_R1,
               self.tot_fcell_kludge, self.tot_neg_curv, ncurv,
               ", ".join(map(str, self.neg_curv_shots))))
        #print("<><><><><><><><> TOP GUN <><><><><><><><>")
        #print("                 End of iteration.")
        if self.testing_mode:
            self.conv_test()

    def get_refined_Bmatrix(self, i_shot):
        return self.UCELL_MAN[i_shot].B_recipspace

    def curvatures(self):
        return self.curv

    def get_correction_misset(self, as_axis_angle_deg=False, anglesXYZ=None, i_shot=None):
        """
        return the current state of the perturbation matrix
        :return: scitbx.matrix sqr
        """
        if anglesXYZ is None:
            assert i_shot is not None
            rx = ry = rz = 0
            if self.refine_Umatrix:
                if self.refine_rotX:
                    rx = self._get_rotX(i_shot)
                if self.refine_rotY:
                    ry = self._get_rotY(i_shot)
                if self.refine_rotZ:
                    rz = self._get_rotZ(i_shot)
            anglesXYZ = rx, ry, rz

        x = col((-1, 0, 0))
        y = col((0, -1, 0))
        z = col((0, 0, -1))
        RX = x.axis_and_angle_as_r3_rotation_matrix(anglesXYZ[0], deg=False)
        RY = y.axis_and_angle_as_r3_rotation_matrix(anglesXYZ[1], deg=False)
        RZ = z.axis_and_angle_as_r3_rotation_matrix(anglesXYZ[2], deg=False)
        M = RX * RY * RZ
        if as_axis_angle_deg:
            q = M.r3_rotation_matrix_as_unit_quaternion()
            rot_ang, rot_ax = q.unit_quaternion_as_axis_and_angle(deg=True)
            return rot_ang, rot_ax
        else:
            return M

    def Fobs_Fref_Rfactor(self, use_binning=False, auto_scale=False):
        if auto_scale:
            # TODO check for convergence of minimizer and warn if it faile, then set scale factor to 1 ?
            self.r1_scale = minimize(GlobalRefiner._rfactor_minimizer_target,
                                     x0=[1], args=(self.Fobs, self.Fref_aligned),
                                     method='Nelder-Mead').x[0]
        else:
            self.r1_scale = 1

        return self.Fobs.r1_factor(self.Fref_aligned,
                                   use_binning=use_binning, scale_factor=self.r1_scale)

    @staticmethod
    def _rfactor_minimizer_target(k, Fobs, Fref):
        return Fobs.r1_factor(Fref, scale_factor=k[0])

    def get_optimized_mtz(self, save_to_file=None, wavelength=1):
        from cctbx import crystal
        # TODO update for non global unit cell case (average over unit cells)

        self._update_Fcell()  # just in case update the Fobs

        um = self.UCELL_MAN[0]
        sym = crystal.symmetry(unit_cell=um.unit_cell_parameters, space_group_symbol=self.symbol)
        mset_obs = miller.set(sym, self.Fobs.indices(), anomalous_flag=True)
        fobs = miller.array(mset_obs, self.Fobs.data()).set_observation_type_xray_amplitude()
        # TODO: what to do in MPI mode when writing ?
        if save_to_file is not None and self.I_AM_ROOT:
            fobs.as_mtz_dataset(column_root_label='fobs', wavelength=wavelength).mtz_object().write(save_to_file)
        return fobs

    def conv_test(self):
        err = []
        s = ""
        A = []
        vars = self._get_ucell_vars(0)
        for i in range(self.n_ucell_param):
            if self.rescale_params:
                a = vars[i]
            else:
                a = self.Xall[self.ucell_xstart[0] + i]

            if i == 3:
                a = a * 180 /PI

            s += "%.4f " % a
            A.append(a)
            err.append(ABS(self.gt_ucell[i] - a))

        mn_err = sum(err) / self.n_ucell_param

        shot_refined = []
        all_det_resid = []
        for i_shot in range(self.n_shots):
            Ctru = self.CRYSTAL_GT[i_shot]
            atru, btru, ctru = Ctru.get_real_space_vectors()
            ang, ax = self.get_correction_misset(as_axis_angle_deg=True, i_shot=i_shot)
            B = self.get_refined_Bmatrix(i_shot=i_shot)
            C = deepcopy(self.CRYSTAL_MODELS[i_shot])
            C.set_B(B)
            if ang > 0:
                C.rotate_around_origin(ax, ang)
            try:
                ang_off = compare_with_ground_truth(atru, btru, ctru,
                                                    [C],
                                                    symbol=self.symbol)[0]
            except RuntimeError:
                ang_off = 999

            out_str = "shot %d: MEAN UCELL ERROR=%.4f, ANG OFF %.4f" % (i_shot, mn_err, ang_off)
            ncells_val = self._get_m_val(i_shot)[0]
            ncells_resid = abs(ncells_val - self.gt_ncells)

            if mn_err < 0.01 and ang_off < 0.004 and ncells_resid < 0.1:
                shot_refined.append(True)
            else:
                shot_refined.append(False)

            if self.refine_detdist:
                det_resid = abs(self.originZ_gt[i_shot] - self._get_originZ_val(i_shot))
                all_det_resid.append(det_resid)
                out_str += ", OrigZ resid = %.4f" % det_resid

            if self.refine_ncells:
                out_str += ", ncells resid=%.4f" % ncells_resid
            print(out_str)

        if all(shot_refined):
            if self.refine_detdist:
                if all([det_resid < 0.01 for det_resid in all_det_resid]):
                    print("OK")
                    exit()
            else:
                print("OK")
                exit()

    # NOTE below are functions which need to be overwritten in the Global MPI class

    def _MPI_sync_hkl_freq(self):
        pass

    def _MPI_sync_fcell_parameters(self):
        pass

    def _data_for_write(self, parameter_dict):
        return [parameter_dict]

    def _MPI_aggregate_model_data_correlations(self):
        self.all_image_corr = [self._get_image_correlation(i) for i in self.shot_ids]
        if self.init_image_corr is None:
            self.init_image_corr = deepcopy(self.all_image_corr)

    def _init_n_bad_shots(self):
        self.n_bad_shots = len(self.bad_shot_list)
        return self.n_bad_shots

    def _init_gather_ang_off(self):
        return self.all_ang_off

    def _get_ang_off(self):
        return self.all_ang_off

    def _MPI_reduce_broadcast(self, var):
        return var
