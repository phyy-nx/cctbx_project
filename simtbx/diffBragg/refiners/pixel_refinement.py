
import scitbx
import numpy as np
from abc import ABCMeta, abstractproperty, abstractmethod
from scitbx.array_family import flex
from scitbx.lbfgs.tst_curvatures import lbfgs_with_curvatures_mix_in
from simtbx.diffBragg.nanoBragg_crystal import nanoBragg_crystal
from scitbx.lbfgs import core_parameters
from cctbx import miller


# used in pixel refinement
class BreakToUseCurvatures(Exception):
    pass


class ReachedMaxIterations(Exception):
    pass


class PixelRefinement(lbfgs_with_curvatures_mix_in):
    """
    This is the base class for pixel refinement based on
    ROI sub-images, where its understood that each sub-image
    contains Bragg scattering
    """

    __metaclass__ = ABCMeta

    run_on_init = False

    def __init__(self):

        self.idx_from_asu = None  # maps global fcell index to asu hkl
        self.asu_from_idx = None   # maps asu hkl to global fcell index
        self.freeze_idx = None  # same length as number of asu indices, whether we freeze it or refine it
        self.rescale_params = False
        self.ignore_line_search_failed_step_at_lower_bound=False

        #optional properties.. make this obvious
        self.FNAMES = None  # dict of {rank_shot_index: image_file_path }
        self.PROC_FNAMES = None  # dict of {rank_shot_index: agg_file_path }
        self.PROC_IDX = None   # dict of {rank_shot_index: agg_file_index }
        self.BBOX_IDX = None   # dict of {rank_bbox_index: agg_file_index }

        self.refine_spectra = False
        self.refine_lambda0 = False
        self.refine_lambda1 = False
        self.n_spectra_param = 0
        self.spectra_coefficients_sigma = 1, 1
        self.spectra_coefficients_init = None

        self.rotX_sigma = 0.003
        self.rotY_sigma = 0.003
        self.rotZ_sigma = 0.003
        self.ucell_sigmas = [0.1, .1]
        self.originZ_sigma = 0.01
        self.m_sigma = 0.05
        self.spot_scale_sigma = 0.0001
        self.a_sigma = 0.05
        self.b_sigma = 0.05
        self.c_sigma = 0.1
        self.fcell_sigma_scale = 0.005
        self.fcell_resolution_bin_Id = None
        self.big_dump = False
        #self.ucell_inits = {0: [79.1, 38.2]} # deprecated, just uses UCELL MANAGERS now 
        self.m_init = {0: 10}  # TODO make setting these properties a requirement
        self.spot_scale_init = {0: 1} # TODO make setting these properties a requirement
        self.print_all_corr=True

        self.pause_after_iteration=0.001

        self.compute_image_model_correlation = False
        self.spot_print_stride = 1000
        self.m = 5  # LBFGS default core parameters
        self.maxfev = 20  # LBFGS default core parameters
        self.gtol = 0.9  # LBFGS default core parameters
        self.xtol = 1.e-16  # LBFGS default core parameters
        self.stpmin = 1.e-20  # LBFGS default core parameters
        self.stpmax = 1.e20  # LBFGS default core parameters
        self.iteratively_freeze_parameters = False  # if true cycle through the various parameter types during each iteration
        self.number_of_frozen_iterations = 10  # how long to freeze parameters before switching to  a new frozen selection
        self.param_sels = None  # this parameters tells the refiner which parameters to freeze next, defined in global_refiner class
        self.trad_conv_eps = 0.05  # LBFGS terminator param converges whern |g| <= max(|x|,1) * trad_conv_eps
        self.drop_conv_max_eps = 1e-5  # LBFGS terminator param not sure, used in the other scitbx lbfgs convergence test
        self.mn_iter = 0  # LBFGS terminator param not sure used in lbfgs
        self.mx_iter = None  # LBFGS terminator param not sure used in lbfgs
        self.max_calls = 100000  # LBFGS terminator param how many overall iterations
        self.diag_mode = "always"  # LBFGS refiner property, whether to update curvatures at each iteration
        self.fix_params_with_negative_curvature = False
        self.request_diag_once = False  # LBFGS refiner property
        self.output_dir = None  # directory to dump progress files, these can be used to restart simulation later
        self.bg_extracted = False  # is using the mode where background is extracted from the image ahead of time and we only fit a coefficient times that extracted value
        self.bg_coef_sigma = .1
        self.only_pass_refined_x_to_lbfgs = False  # if true only passes those parameters being refined to LBFGS
        self.is_being_refined = None  # specifies which parameters are being refined
        self.min_multiplicity = 1  # only refine a spots Fhkl if multiplicity greater than this number
        self.rescale_fcell_by_resolution = True
        self.restart_file = None  # output file from previous run refinement
        self.global_ncells_param = False  # refine one mosaic domain size parameter for all lattices
        self.global_originZ_param = True  # refine one origin for all shots/lattices
        self.global_ucell_param = True  # refine one unit cell for all shots/lattices
        self.scale_r1 = False  # auto scale Fref (reference) to match Fobs when computing R factors
        self.bad_shot_list = []  # deprecated
        self.d = None
        self.fcell_bump = 0.1  # deprecated
        self.filter_bad_shots = False  # deprecated
        self.binner_dmin = 2  # if Fref is not None, then this defines R-factor and CC resolution binner
        self.binner_dmax = 999  # if Fref is not None, then this defines R-factor and CC resolution binner
        self.binner_nbin = 10  # if Fref is not None, then this defines R-factor and CC resolution binner
        self.trial_id = 0  # trial id in case multiple trials are run in sequence
        self.x_init = None  # used to restart the refiner (e.g. self.x gets updated with this)
        self.Fref = None  # place holder for Fhkl reference (for computing R factors during refinement)
        self.plot_fcell = False  # deprecated
        self.bg_offset_only = False  # only refine background offset constant
        self.bg_offset_positive = False  # only allow background offset constant to be positive (recommended if using offset_only)
        self.log_fcells = True  # to refine Fcell using logarithms to avoid negative Fcells
        self.use_curvatures = False  # whether to use the curvatures
        self.testing_mode = False  # Special flag used by the unit tests, ignore
        self.refine_background_planes = False  # whether to refine the background planes
        self.refine_gain_fac = False  # whether to refine the gain factor
        self.refine_ncells = False  # whether to refine Ncells abc
        self.refine_detdist = False  # whether to refine the detdist
        self.refine_Umatrix = False  # whether to refine the Umatrix
        self.refine_Bmatrix = False  # whether to refine the Bmatrx
        self.refine_crystal_scale = False  # whether to refine the crystal scale factor
        self.refine_Fcell = False  # whether to refine Fhkl for each shoebox ROI
        self.refine_rotX = True  # note: only matters if refine_Umatrix is True whether to refine the X rotation
        self.refine_rotY = True  # whether to refine Y rotations
        self.refine_rotZ = True  # whether to refine Z rotations
        self.multi_panel = False  # whether the camera is multi panel or single panel
        self.split_evaluation = False  # whether to use split evaluation run method
        self.recenter=False
        self.hit_break_to_use_curvatures = False  # internal flag if calculating curvatures
        self.refine_Amatrix = False  # whether to refine the  Amatrix (deprecated)
        self.has_pre_cached_roi_data = False  # only for use in global refinement mode
        self.use_curvatures_threshold = 7  # how many positive curvature iterations required before breaking, after which simulation can be restart with use_curvatures=True
        self.curv = None  # curvatures array used internally
        self.print_all_missets = True  # prints out a list of all missetting results (when ground truth is known)
        self.verbose = True  # whether to print during iterations
        self.merge_stat_frequency = 10
        self.print_resolution_bins = True  # whether to print the res bin R factor and CC
        self.plot_images = False  # whether to plot images
        self.iterations = 0  # iteration counter , used internally
        self.FNAMES = {}  # place holder for fnames dictionary so refinement understands layout of the data
        self.gradient_only = False  # parameter for LBFGS run method (internal to the Fortran code, see scitbx.lbfgs.__init__.py method run_c_plus_plus
        self.plot_residuals = False  # whether to plot residuals
        self.debug = False  # for debug print statements
        self.trad_conv = False  # traditional convergenve
        self.calc_curvatures = False  # whether to calc curvatures until a region of positive curvature is reached
        self.plot_statistics = False  # whether to plot stats (global refinement mode)
        self.index_of_displayed_image = 0  # which image to plot
        self.plot_stride = 10  # update plots after this many iterations
        self.plot_spot_stride = 10  # stride for plotting spots on an image
        self.panel_ids = None  # list of panel_ids (same length as roi images, spot_rois, tilt_abc etc)
        self.update_curvatures_every = 3  # every 3 consecutive all positive curvatures we will update them
        self.shot_idx = 0  # place holder because global refinement is across multiple shots
        self.shot_ids = None  # for global refinement ,
        self.poisson_only = True  # use strictly Poissonian statistics
        self.sigma_r = 3  # readout noise mean in ADU
        self.log2pi = np.log(np.pi*2)
        self.use_ucell_priors = False  # (not yet supported) whether to include priors for the unit cell constants
        self.use_rot_priors = False  # (not yet supported) whether to inc;ude priors for misset corrections
        self._refinement_millers = None  # flex array of refinement miller indices (computed by GlobalRefiner _setup method)
        lbfgs_with_curvatures_mix_in.__init__(self, run_on_init=False)

    #@property
    #def m_init(self):
    #    if self.S is not None:
    #        return self.S.crystal.Ncells_abc[0]
    @property
    def refine_lambda0(self):
        return self._refine_lambda0

    @refine_lambda0.setter
    def refine_lambda0(self, val):
        self._refine_lambda0 = val

    @property
    def refine_lambda1(self):
        return self._refine_lambda1

    @refine_lambda1.setter
    def refine_lambda1(self, val):
        self._refine_lambda1 = val

    @property
    def refine_spectra(self):
        return self._refine_spectra

    @refine_spectra.setter
    def refine_spectra(self, val):
        self.refine_lambda0 = val
        self.refine_lambda1 = val
        self._refine_spectra = val

    @property
    def Fref(self):
        """this is a miller array"""
        return self._Fref

    @Fref.setter
    def Fref(self, val):
        if val is not None:
            #C = nanoBragg_crystal()
            #C.miller_array = val  # NOTE: this takes care of expansion to P1
            #val = C.miller_array
            val = val.sort()
        self._Fref = val

    @property
    def resolution_binner(self):
        if self.Fobs is not None:
            return self.Fobs.binner()

    @property
    def Fobs(self):
        """
        refinement updates the internal diffBragg Fhkl tuple directly during refinement, therefore
        if we want an Fobs array we have to manually create it.. This is used for computing
        R factors and CC with the Fhkl reference array, these values are important diagnostics
        when determining how well a refinement is working
        """
        if self.S is not None and self._refinement_millers is not None:
            #indices, amp_data = self.S.D.Fhkl_tuple
            symmetry = self.S.crystal.dxtbx_crystal.get_crystal_symmetry()
            if self.Fref is not None:
                # todo: improve efficiency ? Is this even necessary ?
                symmetry = self.Fref.crystal_symmetry()
                #assert np.allclose(symmetry.unit_cell().parameters(), ref_sym.unit_cell().parameters())
                #assert symmetry.space_group_info().type().hall_symbol() == ref_sym.space_group_info().type().hall_symbol()

            # fobs.customized_copy( space_group_info=self.S.crystal.dxtbx_crystal.get_space_group().info())

            #info = symmetry.space_group_info()
            marray = self.S.D.Fhkl
            marray = marray.customized_copy(crystal_symmetry=symmetry).deep_copy()

            #mset = miller.set(symmetry,
            #                indices=indices, anomalous_flag=True)
            #marray = miller.array(miller_set=mset, data=amp_data).set_observation_type_xray_amplitude()
            #marray = marray.expand_to_p1()
            #marray = marray.generate_bijvoet_mates()

            marray = marray.select_indices(self._refinement_millers).sort()
            marray.setup_binner(d_max=self.binner_dmax, d_min=self.binner_dmin, n_bins=self.binner_nbin)
            return marray
        else:
            return None

    @property
    def _grad_accumulate(self):
        if self.poisson_only:
            return self._poisson_d
        else:
            return self._gaussian_d

    @property
    def _curv_accumulate(self):
        if self.poisson_only:
            return self._poisson_d2
        else:
            return self._gaussian_d2

    @property
    def _target_accumulate(self):
        if self.poisson_only:
            return self._poisson_target
        else:
            return self._gaussian_target

    def _poisson_target(self):
        pass

    def _gaussian_target(self):
        pass

    def _poisson_d(self, d):
        pass

    def _poisson_d2(self, d, d2):
        pass

    def _gaussian_d(self, d):
        pass

    def _gaussian_d2(self, d, d2):
        pass

    @abstractmethod
    def compute_functional_and_gradients(self):
        pass

    @abstractproperty
    def x(self):
        pass

    @abstractproperty
    def n(self):
        pass

    @property
    def plot_images(self):
        return self._plot_images

    @plot_images.setter
    def plot_images(self, val):
        if not isinstance(val, bool):
            raise ValueError("plot_images must be True or False")
        self._plot_images = val

    @property
    def spot_rois(self):
        return self._spot_rois

    @spot_rois.setter
    def spot_rois(self, val):
        if not len(val[0]) == 4:
            raise TypeError("spot_rois should be a list of 4-tuples")
        self._spot_rois = val

    @property
    def n_spots(self):
        try:
            return len(self._spot_rois)
        except AttributeError:
            return None

    @property
    def abc_init(self):
        return self._abc_init

    @abc_init.setter
    def abc_init(self, val):
        if not len(val[0]) == 3:
            raise TypeError("abc_init should be a list of 3-tuples")
        self._abc_init = val

    @property
    def img(self):
        return self._img

    @img.setter
    def img(self, val):
        self._img = val

    @property
    def S(self):
        """An instance of simtbx.diffBragg.sim_data2.SimData, the simulation workhorse"""
        return self._S

    @S.setter
    def S(self, val):
        if not hasattr(val, 'D'):
            print("S should be an instance of SimData after running SimData.instantiate_diffBragg()")
        self._S = val

    @property
    def trad_conv(self):
        return self._trad_conv_test

    @trad_conv.setter
    def trad_conv(self, val):
        self._trad_conv_test = val

    @property
    def trad_conv_eps(self):
        return self._trad_conv_eps

    @trad_conv_eps.setter
    def trad_conv_eps(self, val):
        self._trad_conv_eps = val

    @property
    def drop_conv_max_eps(self):
        return self._drop_conv_max_eps

    @drop_conv_max_eps.setter
    def drop_conv_max_eps(self, val):
        self._drop_conv_max_eps = val

    @property
    def mn_iter(self):
        return self._mn_iter

    @mn_iter.setter
    def mn_iter(self, val):
        self._mn_iter = val

    @property
    def mx_iter(self):
        return self._mx_iter

    @mx_iter.setter
    def mx_iter(self, val):
        self._mx_iter = val

    @property
    def max_calls(self):
        return self._max_calls

    @max_calls.setter
    def max_calls(self, val):
        self._max_calls = val

    @property
    def _terminator(self):
        return scitbx.lbfgs.termination_parameters(
                    traditional_convergence_test=self.trad_conv,
                    traditional_convergence_test_eps=self.trad_conv_eps,
                    drop_convergence_test_max_drop_eps=self.drop_conv_max_eps,
                    min_iterations=self.mn_iter,
                    max_iterations=self.mx_iter,
                    max_calls=self.max_calls)

    @property
    def _core_param(self):
        core_param = core_parameters()
        core_param.gtol = self.gtol
        core_param.xtol = self.xtol
        core_param.stpmin = self.stpmin
        core_param.stpmax = self.stpmax
        core_param.maxfev = self.maxfev
        core_param.m = self.m
        return core_param

    @property
    def _handler(self):
        return scitbx.lbfgs.exception_handling_parameters(
            ignore_line_search_failed_step_at_lower_bound=\
                self.ignore_line_search_failed_step_at_lower_bound)

    def _setup(self):
        """
        Optional place holder for class organization
        This is called just before running the minimizer
        Typically this involves populating the x array
        with initial values and configuring the diffBragg
        instance
        """
        pass

    def run(self, setup=True, setup_only=False):
        """runs the LBFGS minimizer"""

        if setup:
            self._setup()
            self._cache_roi_arrays()
            if setup_only:
                return

        if self.use_curvatures:
            try:
                self.minimizer = scitbx.lbfgs.run(
                    target_evaluator=self,
                    core_params=self._core_param,
                    exception_handling_params=self._handler,
                    termination_params=self._terminator,
                    gradient_only=self.gradient_only)
            except BreakToUseCurvatures:
                self.hit_break_to_use_curvatures = True
                pass

        else:
            try:
                self.diag_mode = None
                self.minimizer = scitbx.lbfgs.run(
                    target_evaluator=self,
                    core_params=self._core_param,
                    exception_handling_params=self._handler,
                    termination_params=self._terminator,
                    gradient_only=self.gradient_only)
            except BreakToUseCurvatures:
                self.hit_break_to_use_curvatures = True
                pass

    def _filter_spot_rois(self):
        """
        This is important to handle the edge case where an ROI occurs along
        the boundary of an image. This arises because
        NanoBragg assumes inclusive ROI bounds, but an exclusive raw_image
        """
        if self.multi_panel:
            nslow, nfast = self.img[0].shape
        else:
            nslow, nfast = self.img.shape
        for i, (_, x2, _, y2) in enumerate(self.spot_rois):
            if x2 == nfast:
                self.spot_rois[i][1] = x2-1  # update roi_xmax
            if y2 == nslow:
                self.spot_rois[i][3] = y2-1  # update roi_ymax

    def _cache_roi_arrays(self):
        """useful cache for iterative LBFGS step"""
        if self.has_pre_cached_roi_data:
            return
        nanoBragg_rois = []  # special nanoBragg format
        xrel, yrel, roi_img = [], [], []
        self._filter_spot_rois()
        for i_roi, (x1, x2, y1, y2) in enumerate(self.spot_rois):
            nanoBragg_rois.append(((x1, x2), (y1, y2)))
            yr, xr = np.indices((y2-y1+1, x2-x1+1))
            xrel.append(xr)
            yrel.append(yr)
            if self.multi_panel:
                pid = self.panel_ids[i_roi]
                roi_img.append(self.img[pid, y1:y2 + 1, x1:x2 + 1])
            else:
                roi_img.append(self.img[y1:y2+1, x1:x2+1])

        self.nanoBragg_rois = nanoBragg_rois
        self.roi_img = roi_img
        self.xrel = xrel
        self.yrel = yrel

    @property
    def roi_img(self):
        """the pixel value in each ROI (2D array)"""
        return self._roi_img

    @roi_img.setter
    def roi_img(self, val):
        self._roi_img = val

    @property
    def nanoBragg_rois(self):
        """rois in the nanoBragg format e.g. ((x1,x2), (y1,y2)"""
        return self._nanoBragg_rois

    @nanoBragg_rois.setter
    def nanoBragg_rois(self, val):
        self._nanoBragg_rois = val

    @property
    def xrel(self):
        """this is the fast-scan coordinate of each pixel in an ROI as 2D array"""
        return self._xrel

    @xrel.setter
    def xrel(self, val):
        self._xrel = val

    @property
    def yrel(self):
        """this is the slow-scan coordinate of each pixel in an ROI as 2D array"""
        return self._yrel

    @yrel.setter
    def yrel(self, val):
        self._yrel = val

    @property
    def use_curvatures(self):
        return self._use_curvatures

    @use_curvatures.setter
    def use_curvatures(self, val):
        if not isinstance(val, bool):
            raise ValueError("use_curvatures should be boolean")
        if val:
            self.calc_curvatures = True
        self._use_curvatures = val

    @property
    def refine_background_planes(self):
        return self._refine_background_planes

    @refine_background_planes.setter
    def refine_background_planes(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_background_planes = val

    @property
    def refine_Amatrix(self):
        return self._refine_Amatrix

    @refine_Amatrix.setter
    def refine_Amatrix(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_Amatrix = val

    @property
    def refine_Umatrix(self):
        return self._refine_Umatrix

    @refine_Umatrix.setter
    def refine_Umatrix(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_Umatrix = val

    @property
    def refine_Bmatrix(self):
        return self._refine_Bmatrix

    @refine_Bmatrix.setter
    def refine_Bmatrix(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_Bmatrix = val

    @property
    def refine_crystal_scale(self):
        return self._refine_crystal_scale

    @refine_crystal_scale.setter
    def refine_crystal_scale(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_crystal_scale = val

    @property
    def refine_gain_fac(self):
        return self._refine_gain_fac

    @refine_gain_fac.setter
    def refine_gain_fac(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_gain_fac = val

    @property
    def refine_detdist(self):
        return self._refine_detdist

    @refine_detdist.setter
    def refine_detdist(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_detdist = val

    @property
    def refine_ncells(self):
        return self._refine_ncells

    @refine_ncells.setter
    def refine_ncells(self, val):
        if not isinstance(val, bool):
            raise ValueError("refine background planes should be a boolean")
        self._refine_ncells = val

    def compute_functional_gradients_diag(self):
        self.f, self.g = self.compute_functional_and_gradients()
        self.d = flex.double(self.curv.as_numpy_array())
        self._verify_diag()
        return self.f, self.g, self.d

