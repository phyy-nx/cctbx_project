from __future__ import division
from cctbx import crystal
from cctbx import xray
from cctbx import sgtbx
import scitbx.math

import iotbx.constraints.commonplace
import iotbx.constraints.geometrical

class crystal_symmetry_builder(object):

  def make_crystal_symmetry(self, unit_cell, space_group):
    self.crystal_symmetry = crystal.symmetry(unit_cell=unit_cell,
                                             space_group=space_group)


class crystal_structure_builder(crystal_symmetry_builder):

  def __init__(self,
               set_grad_flags=True,
               min_distance_sym_equiv=0.5):
    super(crystal_structure_builder, self).__init__()
    self.set_grad_flags = set_grad_flags
    self.min_distance_sym_equiv = min_distance_sym_equiv

  def make_structure(self):
    self.structure = xray.structure(
      special_position_settings=crystal.special_position_settings(
        crystal_symmetry=self.crystal_symmetry,
        min_distance_sym_equiv=self.min_distance_sym_equiv))

  def add_scatterer(self, scatterer, behaviour_of_variable,
                    occupancy_includes_symmetry_factor):
    """ If the parameter set_grad_flags passed to the constructor was True,
        the scatterer.flags.grad_xxx() will be set to True
        if the corresponding variables have been found to be refined
        by the parser using this builder.
    """
    _ = iotbx.constraints.commonplace
    if self.set_grad_flags:
      f = scatterer.flags
      if behaviour_of_variable[0:3].count(_.constant_parameter) != 3:
        f.set_grad_site(True)
      if behaviour_of_variable[3] != _.constant_parameter:
        f.set_grad_occupancy(True)
      if f.use_u_iso():
        if behaviour_of_variable[4] != _.constant_parameter:
          f.set_grad_u_iso(True)
      else:
        if behaviour_of_variable[-6:].count(_.constant_parameter) != 3:
          f.set_grad_u_aniso(True)
    self.structure.add_scatterer(scatterer)

    if occupancy_includes_symmetry_factor:
      sc = self.structure.scatterers()[-1]
      sc.occupancy /= sc.weight_without_occupancy()
      occ = scitbx.math.continued_fraction.from_real(sc.occupancy, eps=1e-5)
      r_occ = occ.as_rational()
      sc.occupancy = round(r_occ.numerator() / r_occ.denominator(), 5)


class constrained_crystal_structure_builder(crystal_structure_builder):

  def __init__(self, constraint_factory=iotbx.constraints.geometrical,
               *args, **kwds):
    super(constrained_crystal_structure_builder, self).__init__(*args, **kwds)
    self.constraint_factory = constraint_factory
    self.geometrical_constraints = []

  def start_geometrical_constraint(self, type_,
                                   bond_length, rotating, stretching,
                                   pivot_relative_pos):
    self.first = len(self.structure.scatterers())

    self.current = type_(rotating=rotating,
                         stretching=stretching,
                         bond_length=bond_length,
                         pivot=self.first + pivot_relative_pos)

  def end_geometrical_constraint(self):
    last = len(self.structure.scatterers())
    self.current.finalise(self.first, last)
    self.geometrical_constraints.append(self.current)

  def finish(self):
    pass
