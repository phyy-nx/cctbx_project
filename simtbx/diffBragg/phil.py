from __future__ import absolute_import, division, print_function

from iotbx.phil import parse

#help_message = '''
#diffBragg command line utility
#'''

simulator_phil = """
simulator {
  oversample = 0
    .type = int
    .help = pixel oversample rate (0 means auto-select)
  device_id = 0
    .type = int
    .help = device id for GPU simulation
  init_scale = 1
    .type = float
    .help = initial scale factor for this crystal simulation
  total_flux = 1e12
    .type = float
    .help = total photon flux for all energies
  crystal {
    ncells_abc = (10,10,10)
      .type = ints(size=3)
      .help = number of unit cells along each crystal axis making up a mosaic domain
    has_isotropic_ncells = False
      .type = bool
      .help = if True, ncells_abc are constrained to be the same values during refinement
    mosaicity = 0
      .type = float
      .help = mosaic spread in degrees
    num_mosaicity_samples = 1
      .type = int
      .help = the number of mosaic domains to use when simulating mosaic spread
  }
  structure_factors {
    mtz_name = None
      .type = str
      .help = path to an MTZ file
    mtz_column = None
      .type = str
      .help = column in an MTZ file
    dmin = 1.5
      .type = float
      .help = minimum resolution for structure factor array
    dmax = 30
      .type = float
      .help = maximum resolution for structure factor array
    default_F = 0
      .type = float
      .help = default value for structure factor amps
  }
  spectrum {
    filename = None
      .type = str
      .help = a .lam file (precognition) for inputting wavelength spectra
    stride = 1
      .type = int 
      .help = stride of the spectrum (e.g. set to 10 to keep every 10th value in the spectrum file data)
  }
  beam {
    size_mm = 1
      .type = float
      .help = diameter of the beam in mm
  }
}
"""

refiner_phil = """
refiner {
  refine_Bmatrix = None
    .type = ints(size_min=1)
    .help = whether to refine the Bmatrix (unit cell parameters)
  refine_Umatrix = None
    .type = ints(size_min=1)
    .help = whether to refine the Umatrix (crystal orientation parameters: rotX, rotY, rotZ)
  refine_ncells = None 
    .type = ints(size_min=1)
    .help = whether to refine the ncells_abc (mosaic domain parameters)
  refine_bg = None 
    .type = ints(size_min=1)
    .help = whether to refine the tilt plane coefficients
  refine_spot_scale = None
    .type = ints(size_min=1)
    .help = whether to refine the crystal scale factor
  refine_spectra = None
    .type = ints(size_min=1)
    .help = whether to refine the two spectra coefficients:  Lambda -> a*Lambda + b
  refine_detdist = None 
    .type = ints(size_min=1)
    .help = whether to refine the detector distance (Z) components
  fix_rotZ = False
    .type = bool
    .help = whether to fix the rotation of the crystal about the Z direction (usually the beam direction)
  max_calls = [100]
    .type = ints(size_min=1)
    .help = maximum number of calls for the refinement trial
  save_models = False
    .type = bool
    .help = whether to save a models file during refinement
  rescale_fcell_by_resolution = False
    .type = bool
    .help = whether to rescale the structure factors according to their resolution
    .help = in an attempt to refine structure factors equally
  init {
    spot_scale = 1
      .type = float
      .help = initial value for spot scale
    ncells_abc = [10, 10, 10]
      .type = floats(size=3)
      .help = initial value for ncells abc that will override params.simulator.crystal.ncells_abc
    spectra_coefficients = [0, 1]
      .type = floats(size=2)
      .help = initial value for spectrum coefficients  Lambda -> c0 + Lambda*c1
  }
  sensitivity {
    rotXYZ = [0.1, 0.1, 0.1]
      .type = floats(size=3)
      .help = refinement sensitivity factor for rotation parameters
    originZ = 0.1
      .type = float
      .help = refinement sensitivity factor for origin Z parameters
    unitcell = [1, 1, 1, 0.1, 0.1, 0.1]
      .type = floats(size=6)
      .help = unit cell parameter sigma values. All 6 must be present, even
      .help = if the crystal system has higher symmetry. 
    ncells_abc = [1, 1, 1]
      .type = floats(size=3)
      .help = refinement sensitivity factor for ncells abc parameters
    spot_scale = 1
      .type = float
      .help = refinement sensitivity factor for crystal scale parameters
    tilt_abc = [0.1, 0.1, 0.1]
      .type = floats(size=3)
      .help = refinement sensitivity factor for tilt plane coefficients
    fcell = 1
      .type = float
      .help = refinement sensitivity factor for fcell parameters
    spectra_coefficients = [0.1, 0.1]
      .type = floats(size=2)
      .help = refinement sensitivity factor for spectrum coefficients
  }
  ranges {
    originZ = [-0.5, 0.5]
      .type = floats(size=2)
      .help = range of values in mm for originZ shift
    spectra0 = [-0.01, 0.01]
      .type = floats(size=2)
      .help = range of values for offset to Lambda correction (Angstrom)
    spectra1 = [-0.95, 1.05]
      .type = floats(size=2)
      .help = range of values for multiplicative Lambda correction
  }
  compute_image_model_correlation = False
    .type = bool
    .help = whether to compute model image intensity correlations
  sigma_r = 3
    .type = float
    .help = standard deviation of the dark signal fluctuation
  adu_per_photon = 1
    .type = float
    .help = how many ADUs (detector units) equal 1 photon
  plot {
    display = False
      .type = bool
      .help = whether to make plots (default is two dimensional heat map plots)
    as_residuals = False
      .type = bool
      .help = whether to plot data minus model
    iteration_stride = 1
      .type = int
      .help = skip this many iterations before updating the plots
  }
  big_dump = False
    .type = bool
    .help = whether to output parameter information
  use_curvatures_threshold = 10
    .type = int
    .help = how many consecutiv positive curvature results before switching to curvature mode
  curvatures = False
    .type = bool
    .help = whether to try using curvatures
  start_with_curvatures = False
    .type = bool
    .help = whether to try using curvatures in the first iteration
  poissononly = False
    .type = bool
    .help = whether to only use poisson statistics (if detector dark signal is negligible)
  tradeps = 1e-2
    .type = float
    .help = LBFGS termination parameter  (smaller means minimize for longer)
  io {
    restart_file = None
      .type = str
      .help = output file for re-starting a simulation
    output_dir = None
      .type = str
      .help = optional output directory
  }
  verbose = False
    .type = bool
    .help = verbosity flag
}
"""

roi_phil = """
roi {
  shoebox_size = 10
    .type = int
    .help = roi box dimension
  reject_edge_reflections = True
    .type = bool
    .help = whether to reject ROIs if they occur near the detector panel edge
  reject_roi_with_hotpix = True
    .type = bool
    .help = whether to reject an ROI if it has a bad pixel
  background_mask = None
    .type = str
    .help = path to a mask specifying background (background pixels set to True)
  hotpixel_mask = None
    .type = str
    .help = path to a hotpixel mask (hot pixels set to True)
}
"""

philz = simulator_phil + refiner_phil + roi_phil
phil_scope = parse(philz)
