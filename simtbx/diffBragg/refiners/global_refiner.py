try:
    from mpi4py import MPI

    comm = MPI.COMM_WORLD
    rank = comm.rank
    size = comm.size
    has_mpi = True
except ImportError:
    rank = 0
    size = 1
    has_mpi = False

if rank == 0:
    import os
    import pandas
    from numpy import mean, median, unique, std
    from tabulate import tabulate
    from scipy.stats import linregress
    from scipy.stats import pearsonr
    from numpy import log as np_log
    from numpy import exp as np_exp
    from numpy import load as np_load
    from numpy import all as np_all
    from numpy.linalg import norm
    from simtbx.diffBragg.refiners import BreakToUseCurvatures
    from scitbx.array_family import flex
    from cctbx.array_family import flex as cctbx_flex
    flex_miller_index = cctbx_flex.miller_index

    flex_double = flex.double
    from scitbx.matrix import col
    from simtbx.diffBragg.refiners import PixelRefinement
    from scipy.optimize import minimize

    from collections import Counter
    import numpy as np

else:
    mean = unique = np_log = np_exp = np_all = norm = median = std = None
    tabulate = None
    flex_miller_index = None
    minimize = None
    np_load = None
    linregress = None
    pearsonr = None
    Counter = None
    # stdout_flush = None
    BreakToUseCurvatures = None
    flex_double = None
    col = None
    PixelRefinement = None

if has_mpi:
    mean = comm.bcast(mean, root=0)
    Counter = comm.bcast(Counter, root=0)
    linregress = comm.bcast(linregress, root=0)
    pearsonr = comm.bcast(pearsonr, root=0)
    tabulate = comm.bcast(tabulate, root=0)
    std = comm.bcast(std, root=0)
    flex_miller_index = comm.bcast(flex_miller_index, root=0)
    median = comm.bcast(median, root=0)
    unique = comm.bcast(unique, root=0)
    np_load = comm.bcast(np_load, root=0)
    np_log = comm.bcast(np_log, root=0)
    np_exp = comm.bcast(np_exp, root=0)
    minimize = comm.bcast(minimize, root=0)
    norm = comm.bcast(norm, root=0)
    np_all = comm.bcast(np_all, root=0)
    # stdout_flush = comm.bcast(stdout_flush)
    BreakToUseCurvatures = comm.bcast(BreakToUseCurvatures)
    flex_double = comm.bcast(flex_double)
    col = comm.bcast(col)
    PixelRefinement = comm.bcast(PixelRefinement)

if rank == 0:
    import pylab as plt

# TODO move me to broadcasts
import sys
import warnings
from copy import deepcopy
from simtbx.diffBragg.utils import compare_with_ground_truth
from cctbx import miller, sgtbx
from IPython import embed

warnings.filterwarnings("ignore")

class FatRefiner(PixelRefinement):

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
                 sgsymbol="P43212"):
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
        """
        PixelRefinement.__init__(self)
        # super(GlobalFat, self).__init__()
        self.num_kludge = 0
        self.global_ncells_param = global_ncells
        self.global_ucell_param = global_ucell
        self.global_originZ_param = global_originZ
        self.debug = False
        self.rot_scale = 1
        self.num_Fcell_kludge = 0
        self.perturb_fcell = perturb_fcell
        # dictionaries whose keys are the shot indices
        self.UCELL_MAN = shot_ucell_managers
        self.CRYSTAL_SCALE_TRUTH = all_crystal_scales  # ground truth of crystal scale factors.. 
        # cache shot ids and make sure they are identical in all other input dicts
        self.shot_ids = sorted(shot_ucell_managers.keys())
        self.big_dump = False
        self.show_watched = False
        self.image_corr = None
        self.n_shots = len(self.shot_ids)
        self.shot_originZ_init = None
        if shot_originZ_init is not None:
            self.shot_originZ_init = self._check_keys(shot_originZ_init)
        # sanity check: no repeats of the same shot
        assert len(self.shot_ids) == len(set(self.shot_ids))

        self.ROIS = self._check_keys(shot_rois)
        self.ASU = self._check_keys(shot_asu)
        self.NANOBRAGG_ROIS = self._check_keys(shot_nanoBragg_rois)
        self.ROI_IMGS = self._check_keys(shot_roi_imgs)
        self.SPECTRA = self._check_keys(shot_spectra)
        self.CRYSTAL_GT = None
        if shot_crystal_GTs is not None:
            self.CRYSTAL_GT = self._check_keys(shot_crystal_GTs)
        self.CRYSTAL_MODELS = self._check_keys(shot_crystal_models)
        self.XREL = self._check_keys(shot_xrel)
        self.YREL = self._check_keys(shot_yrel)
        self.ABC_INIT = self._check_keys(shot_abc_inits)
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
        self._fcell_id = 11  # diffBragg internal index for Fcell derivative manager

        if log_of_init_crystal_scales is None:
            log_of_init_crystal_scales = {s: 0 for s in self.shot_ids}
        else:
            assert sorted(log_of_init_crystal_scales.keys()) == self.shot_ids
        self.log_of_init_crystal_scales = log_of_init_crystal_scales

        self._init_gain = init_gain
        self.num_positive_curvatures = 0
        self._panel_id = None
        self.symbol = sgsymbol

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

    def setup_plots(self):
        if rank == 0:
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
        return self.x, self._f, self._g, self.d

    @property
    def n(self):
        """LBFGS property"""
        return len(self.x)
        #return self.n_total_params

    @property
    def n_global_fcell(self):
        return len(self.idx_from_asu)

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
            raise KeyError("input data funky, check GlobalFat inputs")
        return shot_dict

    def _evaluate_averageI(self):
        """model_Lambda means expected intensity in the pixel"""
        self.model_Lambda = \
            self.gain_fac * self.gain_fac * (self.tilt_plane + self.scale_fac * self.model_bragg_spots)

    def _set_background_plane(self, i_spot):
        xr = self.XREL[self._i_shot][i_spot]
        yr = self.YREL[self._i_shot][i_spot]
        self.a = self.x[self.bg_a_xstart[self._i_shot][i_spot]]
        self.b = self.x[self.bg_b_xstart[self._i_shot][i_spot]]
        self.c = self.x[self.bg_c_xstart[self._i_shot][i_spot]]
        if self.bg_offset_only and self.bg_offset_positive:
            self.c = np_exp(self.c)
        self.tilt_plane = xr * self.a + yr * self.b + self.c

    def _setup(self):
        # Here we go!  https://youtu.be/7VvkXA6xpqI
        if comm.rank == 0:
            print("Setup begins!")
        if not self.asu_from_idx:
            raise ValueError("Need to supply a non empty asu from idx map")
        if not self.idx_from_asu:  # # TODO just derive from its inverse
            raise ValueError("Need to supply a non empty idx from asu map")

        # get the Fhkl information from P1 array internal to nanoBragg
        if comm.rank == 0:
            print("--0 create an Fcell mapping")
        idx, data = self.S.D.Fhkl_tuple
        self.idx_from_p1 = {h: i for i, h in enumerate(idx)}
        # self.p1_from_idx = {i: h for i, h in zip(idx, data)}

        # Make a mapping of panel id to parameter index and backwards
        self.pid_from_idx = {}
        self.idx_from_pid = {}

        # Make the global sized parameter array, though here we only update the local portion
        self.x = flex_double(self.n_total_params)

        # store the starting positions in the parameter array for this shot
        self.rotX_xpos = {}
        self.rotY_xpos = {}
        self.rotZ_xpos = {}
        self.ucell_xstart = {}
        self.ncells_xpos = {}
        self.originZ_xpos = {}
        self.spot_scale_xpos = {}
        self.n_panels = {}
        self.bg_a_xstart = {}
        self.bg_b_xstart = {}
        self.bg_c_xstart = {}
        if comm.rank == 0:
            print("--1 Setting up per shot parameters")

        # this is a sliding parameter that points to the latest local (per-shot) parameter in the x-array
        _local_pos = self.local_idx_start
        for i_shot in self.shot_ids:
            self.pid_from_idx[i_shot] = {i: pid for i, pid in enumerate(unique(self.PANEL_IDS[i_shot]))}
            self.idx_from_pid[i_shot] = {pid: i for i, pid in enumerate(unique(self.PANEL_IDS[i_shot]))}
            self.n_panels[i_shot] = len(self.pid_from_idx[i_shot])

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
                self.x[self.bg_a_xstart[i_shot][i_spot]] = float(a)
                self.x[self.bg_b_xstart[i_shot][i_spot]] = float(b)
                self.x[self.bg_c_xstart[i_shot][i_spot]] = float(c)
                _spot_start += 3

            self.rotX_xpos[i_shot] = self.bg_c_xstart[i_shot][-1] + 1
            self.rotY_xpos[i_shot] = self.rotX_xpos[i_shot] + 1
            self.rotZ_xpos[i_shot] = self.rotY_xpos[i_shot] + 1

            self.x[self.rotX_xpos[i_shot]] = 0
            self.x[self.rotY_xpos[i_shot]] = 0
            self.x[self.rotZ_xpos[i_shot]] = 0

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
                    self.x[self.ucell_xstart[i_shot] + i_cell] = self.UCELL_MAN[i_shot].variables[i_cell]

            if self.global_ncells_param:
                self.ncells_xpos[i_shot] = _global_pos
                _global_pos += self.n_ncells_param
            else:
                self.ncells_xpos[i_shot] = _local_pos
                _local_pos += self.n_ncells_pos
                ncells_xval = np_log(self.S.crystal.Ncells_abc[0]-3)
                # TODO: each shot gets own starting Ncells
                self.x[self.ncells_xpos[i_shot]] = ncells_xval

            if self.global_originZ_param:
                self.originZ_xpos[i_shot] = _global_pos
                _global_pos += 1
            else:
                self.originZ_xpos[i_shot] = _local_pos
                _local_pos += 1
                self.x[self.originZ_xpos[i_shot]] = self.shot_originZ_init[i_shot]

            self.spot_scale_xpos[i_shot] = _local_pos
            _local_pos += 1
            self.x[self.spot_scale_xpos[i_shot]] = self.log_of_init_crystal_scales[i_shot]

        self.fcell_xstart = _global_pos
        self.gain_xpos = self.n_total_params - 1

        # tally up HKL multiplicity
        if comm.rank == 0:
            print("REduction of global data layout")
        hkl_totals = []
        fname_totals = []
        panel_id_totals = []
        # img_totals = []
        for i_shot in self.ASU:
            for i_h, h in enumerate(self.ASU[i_shot]):
                if self.FNAMES is not None:
                    fname_totals.append(self.FNAMES[i_shot])
                panel_id_totals.append(self.PANEL_IDS[i_shot][i_h])
                hkl_totals.append(self.idx_from_asu[h])
                # img_totals.append(self.ROI_IMGS[i_shot][i_h])
        hkl_totals = self._mpi_reduce_broadcast(hkl_totals)

        if rank == 0:
            print("--2 Setting up global parameters")
            # put in estimates for origin vectors
            # TODO: refine at the different hierarchy
            # get te first Z coordinate for now..
            # print("Setting origin: %f " % self.S.detector[0].get_local_origin()[2])
            if self.global_ucell_param:
                # TODO have parameter for global init of unit cell, right now its handled in the global_bboxes scripts
                for i_cell in range(self.n_ucell_param):
                    self.x[self.ucell_xstart[0] + i_cell] = self.UCELL_MAN[0].variables[i_cell]

            if self.global_ncells_param:
                # TODO have parameter for global init of Ncells , right now its handled in the global_bboxes scripts
                ncells_xval = np_log(self.S.crystal.Ncells_abc[0]-3)
                self.x[self.ncells_xpos[0]] = ncells_xval

            if self.global_originZ_param:
                # TODO have parameter for global init of originZ param , right now its handled in the global_bboxes scripts
                self.x[self.originZ_xpos[0]] = self.S.detector[0].get_local_origin()[2]  # NOTE maybe just origin instead?elf.S.detector


            print("----loading fcell data")
            # this is the number of observations of hkl (accessed like a dictionary via global_fcell_index
            print("---- -- counting hkl totes")
            self.hkl_frequency = Counter(hkl_totals)

            # initialize the Fhkl global values
            print("--- --- --- inserting the Fhkl array in the parameter array... ")
            asu_idx = [self.asu_from_idx[idx] for idx in range(self.n_global_fcell)]
            self.refinement_millers = flex_miller_index(tuple(asu_idx))
            Findices, Fdata = self.S.D.Fhkl_tuple
            vals = [Fdata[self.idx_from_p1[h]] for h in asu_idx]  # TODO am I correct/
            if self.log_fcells:
                vals = np_log(vals)
            for i_fcell in range(self.n_global_fcell):
                self.x[self.fcell_xstart + i_fcell] = vals[i_fcell]

            self.Fref_aligned = self.Fref
            if self.Fref is not None:
                self.Fref_aligned = self.Fref.select_indices(self.Fobs.indices())
                self.init_R1 = self.Fobs_Fref_Rfactor(use_binning=False, auto_scale=self.scale_r1)
                print("Initial R1 = %.4f" % self.init_R1)

            if self.output_dir is not None:
                #np.save(os.path.join(self.output_dir, "f_truth"), self.f_truth)  #FIXME by adding in the correct truth from Fref
                np.save(os.path.join(self.output_dir, "f_asu_map"), self.asu_from_idx)

            # set gain TODO: implement gain dependent statistical model ? Per panel or per gain mode dependent ?
            self.x[self.gain_xpos] = self._init_gain  # gain factor
            # n_panels = len(self.S.detector)
            # self.origin_xstart = self.global_param_idx_start
            # for i_pan in range(n_panels):
            #    pid = self.pid_from_idx[i_pan]
            #    self.x[self.origin_xstart + i_pan] = self.S.detector[pid].get_local_origin()[2]
            # lastly, the panel gain correction factor
            # for i_pan in range(n_panels):
            #    self.x[-1] = self._init_gain
            # self.x[-1] = self._init_scale  # initial scale factor

        # reduce then broadcast self.x
        if comm.rank == 0:
            print("--3 combining parameters across ranks")
        self.x = self._mpi_reduce_broadcast(self.x)

        if comm.rank != 0:
            self.hkl_frequency = None
        self.hkl_frequency = comm.bcast(self.hkl_frequency)

        # See if restarting from save state

        if self.x_init is not None:
            self.x = self.x_init
        elif self.restart_file is not None:
            self.x = flex_double(np_load(self.restart_file)["x"])

        if comm.rank == 0:
            print("--4 print initial stats")
            print ("unpack")
        rotx, roty, rotz, uc_vals, ncells_vals, scale_vals, _, origZ = self._unpack_internal(self.x, lst_is_x=True)
        if comm.rank == 0 and self.big_dump:
            print("making frame")

            master_data = {"a": uc_vals[0], "c": uc_vals[1],
                           "Ncells": ncells_vals,
                           "scale": scale_vals,
                           "rotx": rotx,
                           "roty": roty,
                           "rotz": rotz,
                           "origZ": origZ}
            print ("frame")
            master_data = pandas.DataFrame(master_data)
            master_data["gain"] = self.x[self.gain_xpos]
            print('convert to string')
            print(master_data.to_string())

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
        if self.refine_Fcell:
            self.D.refine(self._fcell_id)
        self.D.initialize_managers()

        #if self.testing_mode:

        #    assert comm.size == 1
        #    assert self.global_ucell_param
        #    assert self.global_ncells_param
        #    from copy import deepcopy
        #    import numpy as np
        #    self.x_master = deepcopy(self.x)
        #    sel = np.zeros(len(self.x), bool)
        #    if self.refine_background_planes:
        #        for i in range(n_spots):
        #            sel[self.bg_a_xstart[0][i]] = True
        #            sel[self.bg_b_xstart[0][i]] = True
        #            sel[self.bg_c_xstart[0][i]] = True

        #    if self.refine_ncells:
        #        sel[self.ncells_xpos[0]] = True

        #    if self.refine_detdist:
        #        sel[self.originZ_xpos[0]] = True

        #    if self.refine_Fcell:
        #        sel[self.fcell_xstart: self.fcell_xstart + self.n_global_fcell] = True

        #    if self.refine_Bmatrix:
        #        for i in range(self.n_ucell_param):
        #            sel[self.ucell_xstart[0] + i] = True

        #    if self.refine_Umatrix:
        #        if self.refine_rotX:
        #            sel[self.rotX_xpos[0]] = True
        #        if self.refine_rotY:
        #            sel[self.rotY_xpos[0]] = True
        #        if self.refine_rotZ:
        #            sel[self.rotZ_xpos[0]] = True

        #    if self.refine_crystal_scale:
        #        sel[self.spot_scale_xpos[0]] = True

        #    if self.refine_gain_fac:
        #        sel[self.gain_xpos] = True

        #    from scitbx.array_family import flex
        #    self.refine_sel = flex.bool(sel)
        #    self.x = self.x_master.select(self.refine_sel)

        #    self.refine_sel_pos = np.where(sel)[0]

    def _unpack_internal(self, lst, lst_is_x=False):
        # x = self..as_numpy_array()
        # note n_shots should be specific for this rank
        rotx = [lst[self.rotX_xpos[i_shot]] for i_shot in range(self.n_shots)]
        roty = [lst[self.rotY_xpos[i_shot]] for i_shot in range(self.n_shots)]
        rotz = [lst[self.rotZ_xpos[i_shot]] for i_shot in range(self.n_shots)]
        if self.global_ncells_param:
            ncells_vals = [lst[self.ncells_xpos[0]]] * len(rotx)
        else:
            ncells_vals = [lst[self.ncells_xpos[i_shot]] for i_shot in range(self.n_shots)]

        if self.global_originZ_param:
            originZ_vals = [lst[self.originZ_xpos[0]]] * len(rotx)
        else:
            originZ_vals = [lst[self.originZ_xpos[i_shot]] for i_shot in range(self.n_shots)]

        if lst_is_x:
            ncells_vals = list(np_exp(ncells_vals)+3)
            scale_vals = [np_exp(lst[self.spot_scale_xpos[i_shot]]) for i_shot in range(self.n_shots)]
        else:
            scale_vals = [lst[self.spot_scale_xpos[i_shot]] for i_shot in range(self.n_shots)]
        # this can be used to compare directly
        if self.CRYSTAL_SCALE_TRUTH is not None:
            scale_vals_truths = [self.CRYSTAL_SCALE_TRUTH[i_shot] for i_shot in range(self.n_shots)]
        else:
            scale_vals_truths = None

        # TODO generalize for non tetragonal case
        if self.global_ucell_param:
            ucparams = lst[self.ucell_xstart[0]:self.ucell_xstart[0] + self.n_ucell_param]
            ucparams_lsts = []
            for ucp in ucparams:
                ucparams_lsts.append( [ucp]*len(rotx))
        else:
            ucparams_lsts = []
            for i_uc in range(self.n_ucell_param):
                ucp_lst = [lst[self.ucell_xstart[i_shot] + i_uc] for i_shot in range(self.n_shots)]
                ucparams_lsts.append(ucp_lst)

        rotx = self._mpi_reduce_broadcast(rotx)
        roty = self._mpi_reduce_broadcast(roty)
        rotz = self._mpi_reduce_broadcast(rotz)
        ncells_vals = self._mpi_reduce_broadcast(ncells_vals)
        scale_vals = self._mpi_reduce_broadcast(scale_vals)
        originZ_vals = self._mpi_reduce_broadcast(originZ_vals)

        ucparams_all = []
        for ucp in ucparams_lsts:
            ucp = self._mpi_reduce_broadcast(ucp)
            ucparams_all.append(ucp)
        if scale_vals_truths is not None:
            scale_vals_truths = self._mpi_reduce_broadcast(scale_vals_truths)

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
        self.D.region_of_interest = self.NANOBRAGG_ROIS[self._i_shot][i_spot]
        self.D.add_diffBragg_spots()

    def _update_Fcell(self):
        idx, data = self.S.D.Fhkl_tuple
        for i_fcell in range(self.n_global_fcell):
            # get the asu index and its updated amplitude
            hkl = self.asu_from_idx[i_fcell]
            xpos = self.fcell_xstart + i_fcell
            new_Fcell = self.x[xpos]  # new amplitude
            if self.log_fcells:
                new_Fcell = np_exp(new_Fcell)

            if new_Fcell < 0:  # NOTE this easily happens without the log c.o.v.
                self.x[xpos] = 0
                new_Fcell = 0
                self.num_Fcell_kludge += 1

            # now surgically update the p1 array in nanoBragg with the new amplitudes
            # (need to update each symmetry equivalent)
            sg = sgtbx.space_group(sgtbx.space_group_info(symbol=self.symbol).type().hall_symbol())
            self._sg = sg
            equivs = [i.h() for i in miller.sym_equiv_indices(sg, hkl).indices()]
            for h_equiv in equivs:
                # get the nanoBragg p1 miller table index corresponding to this hkl equivalent
                try:
                    p1_idx = self.idx_from_p1[h_equiv]  # TODO change name to be more specific
                except KeyError as err:
                    if self.debug:
                        print( h_equiv, err)
                    continue
                data[p1_idx] = new_Fcell  # set the data with the new value
        self.S.D.Fhkl_tuple = idx, data  # update nanoBragg again  # TODO: add flag to not re-allocate in nanoBragg!

    def _update_rotXYZ(self):
        if self.refine_rotX:
            self.D.set_value(0, self.rot_scale*self.x[self.rotX_xpos[self._i_shot]])
        if self.refine_rotY:
            self.D.set_value(1, self.rot_scale*self.x[self.rotY_xpos[self._i_shot]])
        if self.refine_rotZ:
            self.D.set_value(2, self.rot_scale*self.x[self.rotZ_xpos[self._i_shot]])

    def _update_ncells(self):
        val = np.exp(self.x[self.ncells_xpos[self._i_shot]])+3
        self.D.set_value(self._ncells_id, val)

    def _update_dxtbx_detector(self):
        # TODO: verify that all panels have same local origin to start with..
        det = self.S.detector
        self.S.panel_id = self._panel_id
        # TODO: select hierarchy level at this point
        # NOTE: what does fast-axis and slow-axis mean for the different hierarchy levels?
        node = det[self._panel_id]
        orig = node.get_local_origin()
        new_originZ = self.x[self.originZ_xpos[self._i_shot]]
        new_local_origin = orig[0], orig[1], new_originZ
        node.set_local_frame(node.get_local_fast_axis(),
                             node.get_local_slow_axis(),
                             new_local_origin)
        self.S.detector = det  # TODO  update the sim_data detector? maybe not necessary after this point
        self.D.update_dxtbx_geoms(det, self.S.beam.nanoBragg_constructor_beam, self._panel_id)

    def _extract_pixel_data(self):
        self.rot_deriv = [0, 0, 0]
        self.rot_second_deriv = [0, 0, 0]
        if self.refine_Umatrix:
            if self.refine_rotX:
                self.rot_deriv[0] = self.rot_scale*self.D.get_derivative_pixels(0).as_numpy_array()
                if self.calc_curvatures:
                    self.rot_second_deriv[0] = self.D.get_second_derivative_pixels(0).as_numpy_array()
            if self.refine_rotY:
                self.rot_deriv[1] = self.rot_scale*self.D.get_derivative_pixels(1).as_numpy_array()
                if self.calc_curvatures:
                    self.rot_second_deriv[1] = self.D.get_second_derivative_pixels(1).as_numpy_array()
            if self.refine_rotZ:
                self.rot_deriv[2] = self.rot_scale*self.D.get_derivative_pixels(2).as_numpy_array()
                if self.calc_curvatures:
                    self.rot_second_deriv[2] = self.D.get_second_derivative_pixels(2).as_numpy_array()

        self.ucell_derivatives = [0] * self.n_ucell_param
        self.ucell_second_derivatives = [0] * self.n_ucell_param
        if self.refine_Bmatrix:
            for i in range(self.n_ucell_param):
                self.ucell_derivatives[i] = self.D.get_derivative_pixels(3 + i).as_numpy_array()
                if self.calc_curvatures:
                    self.ucell_second_derivatives[i] = self.D.get_second_derivative_pixels(3 + i).as_numpy_array()

        self.ncells_deriv = self.detdist_deriv = self.fcell_deriv = 0
        self.ncells_second_deriv = self.detdist_second_deriv = self.fcell_second_deriv = 0
        if self.refine_ncells:
            val = np.exp(self.x[self.ncells_xpos[self._i_shot]])
            self.ncells_deriv = self.D.get_derivative_pixels(self._ncells_id).as_numpy_array()
            self.ncells_deriv *= val
            if self.calc_curvatures:
                self.ncells_second_deriv = self.D.get_second_derivative_pixels(self._ncells_id).as_numpy_array()
                self.ncells_second_deriv *= (val*val)  # NOTE: check me
        if self.refine_detdist:
            self.detdist_deriv = self.D.get_derivative_pixels(self._originZ_id).as_numpy_array()
            if self.calc_curvatures:
                self.detdist_second_deriv = self.D.get_second_derivative_pixels(self._originZ_id).as_numpy_array()
        if self.refine_Fcell:
            self.fcell_deriv = self.D.get_derivative_pixels(self._fcell_id).as_numpy_array()
            if self.calc_curvatures:
                self.fcell_second_deriv = self.D.get_second_derivative_pixels(self._fcell_id).as_numpy_array()

        self.model_bragg_spots = self.D.raw_pixels_roi.as_numpy_array()

    #def _unpack_bgplane_params(self, i_spot):
    #    self.a, self.b, self.c = self.ABC_INIT[self._i_shot][i_spot]

    def _update_ucell(self):
        _s = slice(self.ucell_xstart[self._i_shot], self.ucell_xstart[self._i_shot] + self.n_ucell_param, 1)
        pars = list(self.x[_s])
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

    def compute_functional_and_gradients(self):
        if self.calc_func:
            if self.verbose:
                refine_str= "refining "
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
                
                if self.use_curvatures:
                    
                    print("Trial%d (%s): Compute functional and gradients Iter %d (Using Curvatures)\n<><><><><><><><><><><><><>"
                          % (self.trial_id+1, refine_str, self.iterations + 1))
                else:
                    print("Trial%d (%s): Compute functional and gradients Iter %d PosCurva %d\n<><><><><><><><><><><><><>"
                          % (self.trial_id+1, refine_str, self.iterations + 1, self.num_positive_curvatures))
            if comm.rank == 0 and self.output_dir is not None:
                outf = os.path.join(self.output_dir, "_fcell_trial%d_iter%d" % (self.trial_id, self.iterations))
                fvals = self.x[self.fcell_xstart:self.fcell_xstart + self.n_global_fcell].as_numpy_array()
                np.savez(outf, fvals=fvals, x=self.x.as_numpy_array())

            f = 0
            g = flex_double(self.n)
            if self.calc_curvatures:
                self.curv = flex_double(self.n)

            self.gain_fac = self.x[self.gain_xpos]
            G2 = self.gain_fac ** 2

            self._update_Fcell()  # update the structure factor with the new x

            if self.CRYSTAL_GT is not None:
                all_ang_off = []
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

                    all_ang_off.append(ang_off)

                self.bad_shot_list = list(set(self.bad_shot_list))
                all_ang_off = comm.gather(all_ang_off, root=0)
                self.n_bad_shots = len(self.bad_shot_list)
                self.n_bad_shots = comm.bcast(self.n_bad_shots)

            self.image_corr = [0] * len(self.shot_ids)
            for self._i_shot in self.shot_ids:
                roi_overlay = []
                if self._i_shot in self.bad_shot_list:
                    continue
                self.scale_fac = np_exp(self.x[self.spot_scale_xpos[self._i_shot]])
                expS = self.scale_fac
                # TODO: Omatrix update? All crystal models here should have the same to_primitive operation, ideally
                self._update_beams()
                self._update_umatrix()
                self._update_ucell()
                self._update_ncells()
                self._update_rotXYZ()
                n_spots = len(self.NANOBRAGG_ROIS[self._i_shot])
                for i_spot in range(n_spots):
                    mill_idx = self.ASU[self._i_shot][i_spot]

                    # Only refine me if Im above the threshold multiplicity
                    multi = self.hkl_frequency[self.idx_from_asu[mill_idx]]

                    self._panel_id = self.PANEL_IDS[self._i_shot][i_spot]
                    if self.verbose:
                        print "\rdiffBragg: img %d/%d; spot %d/%d; panel %d" \
                              % (self._i_shot + 1, self.n_shots, i_spot + 1, n_spots, self._panel_id),
                        sys.stdout.flush()

                    self.Imeas = self.ROI_IMGS[self._i_shot][i_spot]
                    self._update_dxtbx_detector()
                    self._run_diffBragg_current(i_spot)
                    self._set_background_plane(i_spot)
                    self._extract_pixel_data()
                    self._evaluate_averageI()

                    # here we can correlate modelLambda with Imeas
                    _overlay_corr, _ = pearsonr(self.Imeas.ravel(), self.model_Lambda.ravel())
                    self.image_corr[self._i_shot] += _overlay_corr
                    if self.poisson_only:
                        self._evaluate_log_averageI()
                    else:
                        self._evaluate_log_averageI_plus_sigma_readout()

                    max_h = tuple(map(int, self.D.max_I_hkl))
                    sg = sgtbx.space_group(sgtbx.space_group_info(self.symbol).type().hall_symbol())
                    refinement_h = self.ASU[self._i_shot][i_spot]
                    equivs = [i.h() for i in miller.sym_equiv_indices(sg, refinement_h).indices()]

                    #if not max_h in equivs:  # TODO understand this more, how does this effect things
                    #    #
                    #    #print("Warning max_h  mismatch!!!!!!")
                    #    #comm.Abort()

                    # helper terms for doing outer derivatives of likelihood function
                    one_over_Lambda = 1. / self.model_Lambda
                    self.one_minus_k_over_Lambda = (1. - self.Imeas * one_over_Lambda)
                    self.k_over_squared_Lambda = self.Imeas * one_over_Lambda * one_over_Lambda

                    self.u = self.Imeas - self.model_Lambda
                    self.one_over_v = 1. / (self.model_Lambda + self.sigma_r ** 2)
                    self.one_minus_2u_minus_u_squared_over_v = 1 - 2 * self.u - self.u * self.u * self.one_over_v

                    f += self._target_accumulate()

                    if self.plot_images and self.iterations % self.plot_stride == 0:
                        if i_spot % self.plot_spot_stride==0:
                            xr = self.XREL[self._i_shot][i_spot]  # fast scan pixels
                            yr = self.YREL[self._i_shot][i_spot]  # slow scan pixels
                            if self.plot_residuals:
                                self.ax.clear()
                                residual = self.model_Lambda - self.Imeas
                                if i_spot == 0:
                                    x = residual.max()
                                else:
                                    x = mean([x, residual.max()])

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

                    if self.refine_background_planes:
                        xr = self.XREL[self._i_shot][i_spot]  # fast scan pixels
                        yr = self.YREL[self._i_shot][i_spot]  # slow scan pixels

                        bg_deriv = [xr*G2, yr*G2, G2]
                        bg_second_deriv = [0, 0, 0]

                        x_positions = [self.bg_a_xstart[self._i_shot][i_spot],
                                       self.bg_b_xstart[self._i_shot][i_spot],
                                       self.bg_c_xstart[self._i_shot][i_spot]]

                        if self.bg_offset_only:
                            bg_offset_x = self.x[self.bg_c_xstart[self._i_shot][i_spot]]
                            # option to only refine C plane

                            x_positions = [x_positions[2]]
                            if self.bg_offset_positive:
                                bg_val = np_exp(bg_offset_x)
                                bg_deriv = [bg_val]
                                bg_second_deriv = [bg_val]  # same as bg_deriv ...
                            else:
                                bg_deriv = [bg_deriv[2]]
                                bg_second_deriv = [bg_second_deriv[2]]

                        for ii, xpos in enumerate(x_positions):
                            d = bg_deriv[ii]
                            g[xpos] += self._grad_accumulate(d)
                            if self.calc_curvatures:
                                d2 = bg_second_deriv[ii]
                                self.curv[xpos] += self._curv_accumulate(d, d2)

                    if self.refine_Umatrix:
                        x_positions = [self.rotX_xpos[self._i_shot],
                                       self.rotY_xpos[self._i_shot],
                                       self.rotZ_xpos[self._i_shot]]
                        for ii, xpos in enumerate(x_positions):
                            d = expS * G2 * self.rot_deriv[ii]
                            g[xpos] += self._grad_accumulate(d)
                            if self.calc_curvatures:
                                d2 = expS * G2 * self.rot_second_deriv[ii]
                                self.curv[xpos] += self._curv_accumulate(d, d2)

                    if self.refine_Bmatrix:
                        # unit cell derivative
                        for i_ucell_p in range(self.n_ucell_param):
                            xpos = self.ucell_xstart[self._i_shot] + i_ucell_p
                            d = expS * G2 * self.ucell_derivatives[i_ucell_p]
                            g[xpos] += self._grad_accumulate(d)

                            if self.calc_curvatures:
                                d2 = expS * G2 * self.ucell_second_derivatives[i_ucell_p]
                                self.curv[xpos] += self._curv_accumulate(d, d2)

                    if self.refine_ncells:
                        d = expS * G2 * self.ncells_deriv
                        xpos = self.ncells_xpos[self._i_shot]
                        g[xpos] += self._grad_accumulate(d)
                        if self.calc_curvatures:
                            d2 = expS * G2 * self.ncells_second_deriv
                            self.curv[xpos] += self._curv_accumulate(d, d2)

                    if self.refine_detdist:
                        d = expS * G2 * self.detdist_deriv
                        xpos = self.originZ_xpos[self._i_shot]
                        g[xpos] += self._grad_accumulate(d)
                        if self.calc_curvatures:
                            d2 = expS * G2 * self.detdist_second_deriv
                            self.curv[xpos] += self._curv_accumulate(d, d2)

                    #    raise NotImplementedError("Cannot refine detdist (yet...)")
                    #    # if self.calc_curvatures:
                    #    #    raise NotImplementedError("Cannot use curvatures and refine detdist (yet...)")
                    #    #origin_xpos = self.origin_xstart + self.idx_from_pid[self._panel_id]
                    #    #g[origin_xpos] += (expS*G2*self.detdist_deriv*one_minus_k_over_Lambda).sum()


                    if self.refine_Fcell and multi >= self.min_multiplicity:
                        xpos = self.fcell_xstart + self.idx_from_asu[self.ASU[self._i_shot][i_spot]]
                        fcell = self.x[xpos]
                        d = expS * G2 * self.fcell_deriv
                        if self.log_fcells:
                            d *= np_exp(fcell)
                        g[xpos] += self._grad_accumulate(d)
                        if self.calc_curvatures:
                            d2 = expS * G2 * self.fcell_second_deriv
                            if self.log_fcells:
                                ex_fcell = np_exp(fcell)
                                d2 = ex_fcell * d + ex_fcell * ex_fcell * d2
                            self.curv[xpos] += self._curv_accumulate(d, d2)

                    if self.refine_crystal_scale:
                        d = G2 * expS * self.model_bragg_spots
                        xpos = self.spot_scale_xpos[self._i_shot]
                        g[xpos] += self._grad_accumulate(d)
                        if self.calc_curvatures:
                            d2 = d
                            self.curv[xpos] += self._curv_accumulate(d, d2)

                    if self.refine_gain_fac:
                        d = 2 * self.gain_fac * (self.tilt_plane + expS * self.model_bragg_spots)
                        g[self.gain_xpos] += self._grad_accumulate(d)
                        if self.calc_curvatures:
                            d2 = d / self.gain_fac
                            self.curv[self.gain_xpos] += self._curv_accumulate(d, d2)

                self.image_corr[self._i_shot] = self.image_corr[self._i_shot] / n_spots


            all_image_corr = comm.reduce(self.image_corr, MPI.SUM, root=0)
            # TODO add in the priors:
            if self.use_ucell_priors and self.refine_Bmatrix:
                for ii in range(self.n_shots):
                    for jj in range(self.n_ucell_param):
                        xpos = self.ucell_xstart[ii] + jj
                        ucell_p = self.x[xpos]
                        sig_square = self.sig_ucell[jj] ** 2
                        f += (ucell_p - self.ave_ucell[jj]) ** 2 / 2 / sig_square
                        g[xpos] += (ucell_p - self.ave_ucell[jj]) / sig_square
                        if self.calc_curvatures:
                            self.curv[xpos] += 1 / sig_square

            if self.use_rot_priors and self.refine_Umatrix:
                for ii in range(self.n_shots):
                    x_positions = [self.rotX_xpos[self._i_shot],
                                   self.rotY_xpos[self._i_shot],
                                   self.rotZ_xpos[self._i_shot]]
                    for xpos in x_positions:
                        rot_p = self.x[xpos]
                        sig_square = self.sig_rot ** 2
                        f += rot_p ** 2 / 2 / sig_square
                        g[xpos] += rot_p / sig_square
                        if self.calc_curvatures:
                            self.curv[xpos] += 1 / sig_square

            # reduce the broadcast summed results:
            if comm.rank == 0:
                print("\nMPI reduce on functionals and gradients...")
            f = self._mpi_reduce_broadcast(f)
            g = self._mpi_reduce_broadcast(g)
            self.rotx, self.roty, self.rotz, self.uc_vals, self.ncells_vals, self.scale_vals, \
                self.scale_vals_truths, self.origZ_vals = self._unpack_internal(self.x, lst_is_x=True)
            self.Grotx, self.Groty, self.Grotz, self.Guc_vals, self.Gncells_vals, self.Gscale_vals, _, self.GorigZ_vals = \
                self._unpack_internal(g, lst_is_x=False)
            if self.calc_curvatures:
                self.curv = self._mpi_reduce_broadcast(self.curv)
                self.CUrotx, self.CUroty, self.CUrotz, self.CUuc_vals, self.CUncells_vals, self.CUscale_vals, _, self.CUorigZ_vals = \
                    self._unpack_internal(self.curv, lst_is_x=False)
            self.tot_fcell_kludge = self._mpi_reduce_broadcast(self.num_Fcell_kludge)
            self.tot_neg_curv = 0
            self.neg_curv_shots = []
            if self.calc_curvatures:
                self.tot_neg_curv = sum(self.curv < 0)

            self._f = f
            self._g = g
            self.g = g

            if self.calc_curvatures and not self.use_curvatures:
                if np_all(self.curv.as_numpy_array() >= 0):
                    self.num_positive_curvatures += 1
                    self.d = flex_double(self.curv.as_numpy_array())
                    self._verify_diag()
                else:
                    self.num_positive_curvatures = 0
                    self.d = None

            if self.use_curvatures:
                if np_all(self.curv.as_numpy_array() >= 0):
                    self.request_diag_once = False
                    self.d = flex_double(self.curv.as_numpy_array())
                    self._verify_diag()
                else:
                    if self.debug:
                        print("\n**************************************")
                        print("**************************************")
                        print("**************************************")
                        print("**************************************")
                        print("\tFIXING CURVA: ATTEMPTING DISASTER AVERSION")
                        print("*nn***************************************")
                        print("*nn***************************************")
                        print("*nn***************************************")
                        print("*nn***************************************")
            else:
                self.d = None

            self.D.raw_pixels *= 0
            self.gnorm = norm(g)

            if self.verbose:
                if self.CRYSTAL_GT is not None:
                    all_ang_off = [s for sl in all_ang_off for s in sl]  # flatten the gathered array
                    n_broken_misset = sum([ 1 for aa in all_ang_off if aa == -1])
                    n_bad_misset = sum([ 1 for aa in all_ang_off if aa > 0.1])
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
                        all_ang_off = ["%.5f" % aa for aa in all_ang_off]
                        print(", ".join(all_ang_off))
                        print ("N shots deemed bad from missets: %d" % self.n_bad_shots)
                    print("MISSETTING median: %.4f; mean: %.4f, max: %.4f, min %.4f, num > .1 deg: %d/%d; num broken=%d"
                          % (misset_median, misset_mean,misset_max, misset_min, n_bad_misset, n_misset, n_broken_misset))

                all_corr_str = ["%.2f" % ic for ic in all_image_corr]
                print"Correlation stats:"
                print(", ".join(all_corr_str))
                print"---------------"
                n_bad_corr = sum([1 for ic in all_image_corr if ic < 0.25])
                print("CORRELATION median: %.4f; mean: %.4f, max: %.4f, min %.4f, num <.25: %d/%d;"
                      % (median(all_image_corr), mean(all_image_corr), max(all_image_corr), min(all_image_corr), n_bad_corr, len(all_image_corr) ))
                
                self.print_step()
                self.print_step_grads()
            self.iterations += 1
            self.f_vals.append(f)

            #if self.testing_mode:
            #    self.x = self.x_master.select(self.refine_sel)
            #    self._g = self._g.select(self.refine_sel)
            #    if self.d is not None:
            #        self.d = self.d.select(self.refine_sel)
            #    self.g = self.g.select(self.refine_sel)

            if self.calc_curvatures and not self.use_curvatures:
                if self.num_positive_curvatures == self.use_curvatures_threshold:
                    raise BreakToUseCurvatures
        return self._f, self._g

    def _mpi_reduce_broadcast(self, var):
        var = comm.reduce(var, MPI.SUM, root=0)
        var = comm.bcast(var, root=0)
        return var

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
        fterm = .5 * (self.log2pi + 2*self.log_Lambda_plus_sigma_readout + self.u * self.u * self.one_over_v).sum()
        return fterm

    def _gaussian_d(self, d):
        gterm = .5 * (d * self.one_over_v * self.one_minus_2u_minus_u_squared_over_v).sum()
        return gterm

    def _gaussian_d2(self, d, d2):
        cterm = self.one_over_v * (d2 * self.one_minus_2u_minus_u_squared_over_v -
                                   d * d * (self.one_over_v * self.one_minus_2u_minus_u_squared_over_v -
                                            (
                                                        2 + 2 * self.u * self.one_over_v + self.u * self.u * self.one_over_v * self.one_over_v)))
        cterm = .5 * cterm.sum()
        return cterm

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
        L = self.model_Lambda + self.sigma_r ** 2
        L_is_neg = (L <= 0).ravel()
        if any(L_is_neg):
            self.num_kludge += 1
            print("\n<><><><><><><><>\n\tWARNING: NEGATIVE INTENSITY IN MODEL!!!!!!!!!\n<><><><><><><><><>\n")
        #    raise ValueError("model of Bragg spots cannot have negative intensities...")
        self.log_Lambda_plus_sigma_readout = np_log(L)
        self.log_Lambda_plus_sigma_readout[L <= 0] = 0  # but will I ever kludge ?

    def print_step(self):
        """Deprecated"""
        names = self.UCELL_MAN[self._i_shot].variable_names
        vals = self.UCELL_MAN[self._i_shot].variables
        ucell_labels = []
        for n, v in zip(names, vals):
            ucell_labels.append('%s=%+2.7g' % (n, v))
        rotX = self.rot_scale*self.x[self.rotX_xpos[self._i_shot]]
        rotY = self.rot_scale*self.x[self.rotY_xpos[self._i_shot]]
        rotZ = self.rot_scale*self.x[self.rotZ_xpos[self._i_shot]]
        rot_labels = ["rotX=%+3.7g" % rotX, "rotY=%+3.7g" % rotY, "rotZ=%+3.4g" % rotZ]

        if self.refine_Umatrix or self.refine_Bmatrix or self.refine_crystal_scale or self.refine_ncells:

            master_data = {"Ncells": self.ncells_vals,
                           "scale": self.scale_vals,
                           "rotx": self.rotx,
                           "roty": self.roty,
                           "rotz": self.rotz, "origZ": self.origZ_vals}
            for i_uc in range(self.n_ucell_param):
                master_data["uc%d" % i_uc] = self.uc_vals[i_uc]


            master_data = pandas.DataFrame(master_data)
            master_data["gain"] = self.x[self.gain_xpos]
            if self.big_dump:
                print(master_data.to_string(float_format="%2.7g"))

    def print_step_grads(self):

        names = self.UCELL_MAN[self._i_shot].variable_names
        vals = self.UCELL_MAN[self._i_shot].variables
        ucell_labels = []
        for i, (n, v) in enumerate(zip(names, vals)):
            grad = self._g[self.ucell_xstart[self._i_shot] + i]
            ucell_labels.append('G%s=%+2.7g' % (n, grad))
        rotX = self._g[self.rotX_xpos[self._i_shot]]
        rotY = self._g[self.rotY_xpos[self._i_shot]]
        rotZ = self._g[self.rotZ_xpos[self._i_shot]]
        rot_labels = ["GrotX=%+3.7g" % rotX, "GrotY=%+3.7g" % rotY, "GrotZ=%+3.4g" % rotZ]
        xnorm = norm(self.x)

        if self.big_dump:
            master_data ={"GNcells": self.Gncells_vals,
                           "Gscale": self.Gscale_vals,
                           "Grotx": self.Grotx,
                           "Groty": self.Groty,
                           "Grotz": self.Grotz, "GorigZ": self.GorigZ_vals}
            for i_uc in range(self.n_ucell_param):
                master_data["Guc%d" %i_uc]= self.Guc_vals[i_uc]
            master_data = pandas.DataFrame(master_data)
            master_data["Ggain"] = self._g[self.gain_xpos]
            print(master_data.to_string(float_format="%2.7g"))

        if self.calc_curvatures:
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
                if self.big_dump:
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
            scale_resid = [np.abs(s-stru) for s, stru in zip(_sv, self.scale_vals_truths)]
            scale_stats_string += ", truth_resid=%.4f" % np.median(scale_resid)

        # TODO : use a median for a vals if refining Ncells per shot or unit cell per shot
        scale_stats_string += ", Ncells=%.3f" % self.ncells_vals[0]
        uc_string = ", "
        ucparam_names = self.UCELL_MAN[0].variable_names
        for i_ucparam, ucparam_lst in enumerate(self.uc_vals):
            param_val = median(ucparam_lst)
            uc_string += "%s=%.3f, " % (ucparam_names[i_ucparam], param_val)
        scale_stats_string += uc_string
        scale_stats_string += "originZ=%f, " % np.median(self.origZ_vals)

        Xnorm = norm(self.x)
        R1 = -1
        R1_i = -1
        ncurv = 0
        if self.calc_curvatures:
            ncurv = len(self.curv)

        stat_bins_str = ""
        Istat_bins_str = ""
        print(
                    "\t|G|=%f, eps*|X|=%f, R1=%2.7g (R1 at start=%2.7g), Fcell kludges=%d, Neg. Curv.: %d/%d on shots=%s\n%s\n%s\n%s"
                    % (self.gnorm, Xnorm * self.trad_conv_eps, R1, R1_i, self.tot_fcell_kludge, self.tot_neg_curv, ncurv,
                       ", ".join(map(str, self.neg_curv_shots)), scale_stats_string, stat_bins_str,  Istat_bins_str))

        if self.Fref is not None:
            print("R-factor overall:")
            print self.Fobs_Fref_Rfactor(use_binning=False, auto_scale=self.scale_r1)
            print("R-factor (shells):")
            print self.Fobs_Fref_Rfactor(use_binning=True, auto_scale=self.scale_r1).show()
            print("CC overall:")
            print self.Fobs.correlation(self.Fref_aligned)
            print("CC:")
            self.Fobs.correlation(self.Fref_aligned, use_binning=True).show()
            print("<><><><><><><><> TOP GUN <><><><><><><><>")
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
                    rx = self.rot_scale*self.x[self.rotX_xpos[i_shot]]
                if self.refine_rotY:
                    ry = self.rot_scale*self.x[self.rotY_xpos[i_shot]]
                if self.refine_rotZ:
                    rz = self.rot_scale*self.x[self.rotZ_xpos[i_shot]]

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
            self.r1_scale = minimize(FatRefiner._rfactor_minimizer_target,
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
        if save_to_file is not None and comm.rank == 0:
            fobs.as_mtz_dataset(column_root_label='fobs', wavelength=wavelength).mtz_object().write(save_to_file)
        return fobs

    def conv_test(self):
        err = []
        s = ""
        A = []
        for i in range(self.n_ucell_param):
            a = self.x[self.ucell_xstart[0] + i]
            if i == 3:
                a = a * 180 / np.pi
            s += "%.4f " % a
            A.append(a)
            err.append(np.abs(self.gt_ucell[i] - a))

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

            print "shot %d: MEAN ERROR=%.4f, ANG OFF %.4f" % (i_shot, mn_err, ang_off)
            ncells_val = np.exp(self.x[self.ncells_xpos[i_shot]]) + 3
            ncells_resid = abs(ncells_val - self.gt_ncells)

            if mn_err < 0.01 and ang_off < 0.004 and ncells_resid < 0.1:
                shot_refined.append(True)
            else:
                shot_refined.append(False)

            if self.refine_detdist:
                det_resid = abs(self.originZ_gt[i_shot] - self.x[self.originZ_xpos[i_shot]])
                print "Origin Z truth: %f" % self.originZ_gt[i_shot]
                print "Origin Z current: %f" % self.x[self.originZ_xpos[i_shot]]
                all_det_resid.append(det_resid)

        if all(shot_refined):
            if self.refine_detdist:
                if all([det_resid < 0.01 for det_resid in all_det_resid]):
                    print "OK"
                    exit()
            else:
                print "OK"
                exit()
