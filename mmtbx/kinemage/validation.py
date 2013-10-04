from __future__ import division
import os, string
from iotbx import pdb
from mmtbx import monomer_library
from mmtbx.chemical_components import get_bond_pairs
from mmtbx.validation.rotalyze import rotalyze
from mmtbx.validation.ramalyze import ramalyze
from mmtbx.validation.cbetadev import cbetadev
from mmtbx.validation.rna_validate import rna_validate
from mmtbx.kinemage import kin_vec
from iotbx.pdb import common_residue_names_get_class
from libtbx import easy_run
from scitbx import matrix
from cctbx import geometry_restraints
from mmtbx.monomer_library import pdb_interpretation
from mmtbx.monomer_library import rna_sugar_pucker_analysis
from iotbx.pdb.rna_dna_detection import residue_analysis
import iotbx.phil
from libtbx.utils import Sorry, Usage
from libtbx.str_utils import show_string

def get_master_phil():
  return iotbx.phil.parse(
    input_string="""
      kinemage {
        pdb = None
         .type = path
         .optional = True
         .help = '''Enter a PDB file name'''
        cif = None
         .type = path
         .optional = True
         .multiple = True
         .help = '''Enter a CIF file for ligand parameters'''
        out_file = None
         .type = path
         .optional = True
         .help = '''Enter a .kin output name'''
        keep_hydrogens = False
        .type = bool
        .help = '''Keep hydrogens in input file'''
  }
    """)

def build_name_hash(pdb_hierarchy):
  i_seq_name_hash = dict()
  for atom in pdb_hierarchy.atoms():
    i_seq_name_hash[atom.i_seq]=atom.pdb_label_columns()
  return i_seq_name_hash

def get_angle_outliers(angle_proxies, chain, sites_cart, hierarchy):
  i_seq_name_hash = build_name_hash(pdb_hierarchy=hierarchy)
  kin_text = "@subgroup {geom devs} dominant\n"
  for ap in angle_proxies:
    restraint = geometry_restraints.angle(sites_cart=sites_cart,
                                          proxy=ap)
    res = i_seq_name_hash[ap.i_seqs[0]][5:]
    altloc = i_seq_name_hash[ap.i_seqs[0]][4:5].lower()
    cur_chain = i_seq_name_hash[ap.i_seqs[0]][8:10]
    if chain.id.strip() is not cur_chain.strip():
      continue
    atom1 = i_seq_name_hash[ap.i_seqs[0]][0:4].strip()
    atom2 = i_seq_name_hash[ap.i_seqs[1]][0:4].strip()
    atom3 = i_seq_name_hash[ap.i_seqs[2]][0:4].strip()
    if atom1[0] == "H" or atom2[0] == "H" or atom3[0] == "H":
      continue
    sigma = ((1/restraint.weight)**(.5))
    num_sigmas = - (restraint.delta / sigma) #negative to match MolProbity direction
    if abs(num_sigmas) >= 4.0:
      angle_key = altloc+res[0:3].lower()+res[3:]+' '+atom1.lower()+ \
                  '-'+atom2.lower()+'-'+atom3.lower()
      kin = add_fan(sites=restraint.sites,
                    delta=restraint.delta,
                    num_sigmas=num_sigmas,
                    angle_key=angle_key)
      kin_text += kin
  return kin_text

def get_bond_outliers(bond_proxies, chain, sites_cart, hierarchy):
  i_seq_name_hash = build_name_hash(pdb_hierarchy=hierarchy)
  kin_text = "@subgroup {length devs} dominant\n"
  for bp in bond_proxies.simple:
    restraint = geometry_restraints.bond(sites_cart=sites_cart,
                                         proxy=bp)
    res = i_seq_name_hash[bp.i_seqs[0]][5:]
    altloc = i_seq_name_hash[bp.i_seqs[0]][4:5].lower()
    cur_chain = i_seq_name_hash[bp.i_seqs[0]][8:10]
    if chain.id.strip() is not cur_chain.strip():
      continue
    atom1 = i_seq_name_hash[bp.i_seqs[0]][0:4].strip()
    atom2 = i_seq_name_hash[bp.i_seqs[1]][0:4].strip()
    if atom1[0] == "H" or atom2[0] == "H" or \
       atom1[0] == "D" or atom2[0] == "D":
      continue
    sigma = ((1/restraint.weight)**(.5))
    num_sigmas = -(restraint.delta / sigma) #negative to match MolProbity direction
    if abs(num_sigmas) >= 4.0:
      bond_key = altloc+res[0:3].lower()+res[3:]+\
                 ' '+atom1.lower()+'-'+atom2.lower()
      print bond_key, num_sigmas
      kin = add_spring(sites=restraint.sites,
                       num_sigmas=num_sigmas,
                       bond_key=bond_key)
      kin_text += kin
  return kin_text

def add_fan(sites, delta, num_sigmas, angle_key):
  kin_text = ""
  angle_key_full = "%s %.3f sigma" % (angle_key, num_sigmas)
  if num_sigmas < 0:
    color = "blue"
  else:
    color = "red"
  a = matrix.col(sites[0])
  b = matrix.col(sites[1])
  c = matrix.col(sites[2])
  normal = (a-b).cross(c-b).normalize()
  r = normal.axis_and_angle_as_r3_rotation_matrix(angle=delta, deg=True)
  new_c = tuple( (r*(c-b)) +b)
  kin_text += "@vectorlist {%s} color= %s width= 4 master= {angle dev}\n" \
               % (angle_key_full, color)
  kin_text += kin_vec(angle_key_full,sites[0],angle_key_full,sites[1])
  kin_text += kin_vec(angle_key_full,sites[1],angle_key_full,new_c)

  r = normal.axis_and_angle_as_r3_rotation_matrix(angle=(delta*.75), deg=True)
  new_c = tuple( (r*(c-b)) +b)
  kin_text += "@vectorlist {%s} color= %s width= 3 master= {angle dev}\n" \
               % (angle_key_full, color)
  kin_text += kin_vec(angle_key_full,sites[1],angle_key,new_c)

  r = normal.axis_and_angle_as_r3_rotation_matrix(angle=(delta*.5), deg=True)
  new_c = tuple( (r*(c-b)) +b)
  kin_text += "@vectorlist {%s} color= %s width= 2 master= {angle dev}\n" \
               % (angle_key_full, color)
  kin_text += kin_vec(angle_key_full,sites[1],angle_key,new_c)

  r = normal.axis_and_angle_as_r3_rotation_matrix(angle=(delta*.25), deg=True)
  new_c = tuple( (r*(c-b)) +b)
  kin_text += "@vectorlist {%s} color= %s width= 1 master= {angle dev}\n" \
              % (angle_key_full, color)
  kin_text += kin_vec(angle_key_full,sites[1],angle_key,new_c)

  return kin_text

def add_spring(sites, num_sigmas, bond_key):
  kin_text = ""
  if num_sigmas < 0:
    color = "blue"
  else:
    color = "red"
  a = matrix.col(sites[0])
  b = matrix.col(sites[1])
  c = matrix.col( (1,0,0) )
  normal = ((a-b).cross(c-b).normalize())*0.2
  current = a+normal
  new = tuple(current)
  kin_text += "@vectorlist {%s %.3f sigma} color= %s width= 3 master= {length dev}\n" \
              % (bond_key, num_sigmas, color)
  bond_key_long = "%s %.3f sigma" % (bond_key, num_sigmas)
  kin_text += kin_vec(bond_key_long,sites[0],bond_key_long,new)
  angle = 36
  dev = num_sigmas
  if dev > 10.0:
    dev = 10.0
  if dev < -10.0:
    dev = -10.0
  if dev <= 0.0:
    angle += 1.5*abs(dev)
  elif dev > 0.0:
    angle -= 1.5*dev
  i = 0
  n = 60
  axis = b-a
  step = axis*(1.0/n)
  r = axis.axis_and_angle_as_r3_rotation_matrix(angle=angle, deg=True)
  while i < n:
    next = (r*(current-b) +b)
    next = next + step
    kin_text += kin_vec(bond_key_long,tuple(current),bond_key_long,tuple(next))
    current = next
    i += 1
  kin_text += kin_vec(bond_key_long,tuple(current),bond_key_long,sites[1])
  return kin_text

def get_residue_bonds(residue):
  if residue is None: return []
  if residue is False: return []
  if residue in never_do_residues: return []
  monomer_lib_entry = mon_lib_query(residue)
  ml = mon_lib_query(residue)
  if ml is None: return []
  bonds = []
  for bond in ml.bond_list:
    bonds.append([bond.atom_id_1, bond.atom_id_2])
  return bonds

def make_probe_dots(hierarchy, keep_hydrogens=False):
  probe = \
    'phenix.probe -4H -quiet -noticks -nogroup -dotmaster -mc -self "ALL" -'
  trim = "phenix.reduce -quiet -trim -"
  build = "phenix.reduce -oh -his -flip -pen9999 -keep -allalt -"
  probe_return = ""
  for i,m in enumerate(hierarchy.models()):
    r = pdb.hierarchy.root()
    mdc = m.detached_copy()
    r.append_model(mdc)
    if keep_hydrogens is False:
      clean_out = easy_run.fully_buffered(trim,
                                  stdin_lines=r.as_pdb_string())
      build_out = easy_run.fully_buffered(build,
                                  stdin_lines=clean_out.stdout_lines)
      input_str = string.join(build_out.stdout_lines, '\n')
    else:
      input_str = r.as_pdb_string()
    probe_out = easy_run.fully_buffered(probe,
                         stdin_lines=input_str).stdout_lines
    for line in probe_out:
      probe_return += line+'\n'
  return probe_return

def cbeta_dev (outliers, chain_id=None) :
  cbeta_out = "@subgroup {CB dev} dominant\n"
  cbeta_out += "@balllist {CB dev Ball} color= gold radius= 0.0020   master= {Cbeta dev}\n"
  for outlier in outliers :
    if (chain_id is None) or (chain_id == outlier.chain_id) :
      cbeta_out += outlier.as_kinemage() + "\n"
  if len(cbeta_out.splitlines()) == 2:
    cbeta_out = ""
  return cbeta_out

def midpoint(p1, p2):
  mid = [0.0, 0.0, 0.0]
  mid[0] = (p1[0]+p2[0])/2
  mid[1] = (p1[1]+p2[1])/2
  mid[2] = (p1[2]+p2[2])/2
  return mid

def pperp_outliers(hierarchy, chain):
  kin_out = "@vectorlist {ext} color= magenta master= {base-P perp}\n"
  rv = rna_validate()
  outliers = rv.pucker_evaluate(hierarchy=hierarchy)
  params=rv.params.rna_validate.rna_sugar_pucker_analysis
  outlier_key_list = []
  for outlier in outliers:
    outlier_key_list.append(outlier[0])
  for conformer in chain.conformers():
    for residue in conformer.residues():
      if common_residue_names_get_class(residue.resname) != "common_rna_dna":
        continue
      ra1 = residue_analysis(
                             residue_atoms=residue.atoms(),
                             distance_tolerance=params.bond_detection_distance_tolerance)
      if (ra1.problems is not None): continue
      if (not ra1.is_rna): continue
      try:
        key = residue.find_atom_by(name=" C1'").pdb_label_columns()[4:]
      except Exception:
        continue
      if key in outlier_key_list:
        if rv.pucker_perp_xyz[key][0] is not None:
          perp_xyz = rv.pucker_perp_xyz[key][0] #p_perp_xyz
        else:
          perp_xyz = rv.pucker_perp_xyz[key][1] #o3p_perp_xyz
        if rv.pucker_dist[key][0] is not None:
          perp_dist = rv.pucker_dist[key][0]
          if perp_dist < 2.9:
            pucker_text = " 2'?"
          else:
            pucker_text = " 3'?"
        else:
          perp_dist = rv.pucker_dist[key][1]
          if perp_dist < 2.4:
            pucker_text = " 2'?"
          else:
            pucker_text = " 3'?"
        key = key[0:4].lower()+key[4:]
        key += pucker_text
        kin_out += kin_vec(key, perp_xyz[0], key, perp_xyz[1])
        a = matrix.col(perp_xyz[1])
        b = matrix.col(residue.find_atom_by(name=" C1'").xyz)
        c = (a-b).normalize()
        new = a-(c*.8)
        kin_out += kin_vec(key, perp_xyz[1], key, tuple(new), 4)
        new = a+(c*.4)
        kin_out += kin_vec(key, perp_xyz[1], key, tuple(new), 4)
        r_vec = matrix.col(perp_xyz[1]) - matrix.col(perp_xyz[0])
        r = r_vec.axis_and_angle_as_r3_rotation_matrix(angle=90, deg=True)
        new = r*(new-a)+a
        kin_out += kin_vec(key, perp_xyz[1], key, tuple(new), 4)
        r = r_vec.axis_and_angle_as_r3_rotation_matrix(angle=180, deg=True)
        new = r*(new-a)+a
        kin_out += kin_vec(key, perp_xyz[1], key, tuple(new), 4)
  return kin_out

def rama_outliers(chain, pdbID, ram_outliers):
  ram_out = "@subgroup {Rama outliers} master= {Rama outliers}\n"
  ram_out += "@vectorlist {bad Rama Ca} width= 4 color= green\n"
  outlier_list = []
  for outlier in ram_outliers.results :
    if outlier.chain_id == chain.id :
      ram_out += outlier.as_kinemage()
  return ram_out

def rotamer_outliers(chain, pdbID, rot_outliers):
  mc_atoms = ["N", "C", "O", "OXT"]
  rot_out = "@subgroup {Rota outliers} dominant\n"
  rot_out += "@vectorlist {chain %s} color= gold  master= {Rota outliers}\n" % chain.id
  outlier_list = []
  for outlier in rot_outliers.results :
    if (not outlier.is_outlier()) : continue
    outlier_list.append(outlier.atom_group_id_str())
  for residue_group in chain.residue_groups():
    for atom_group in residue_group.atom_groups() :
      check_key = atom_group.id_str()
      if (check_key in outlier_list) :
        key_hash = {}
        xyz_hash = {}
        for atom in atom_group.atoms():
          key = "%s %s %s%s  B%.2f %s" % (
              atom.name.lower(),
              atom_group.resname.lower(),
              chain.id,
              residue_group.resid(),
              atom.b,
              pdbID)
          key_hash[atom.name.strip()] = key
          xyz_hash[atom.name.strip()] = atom.xyz
        bonds = get_bond_pairs(code=atom_group.resname)
        for bond in bonds:
          if bond[0] in mc_atoms or bond[1] in mc_atoms:
            continue
          elif bond[0].startswith('H') or bond[1].startswith('H'):
            continue
          rot_out += kin_vec(key_hash[bond[0]],
                           xyz_hash[bond[0]],
                           key_hash[bond[1]],
                           xyz_hash[bond[1]])
  if len(rot_out.splitlines()) == 2:
    rot_out = ""
  return rot_out

def get_chain_color(index):
  chain_colors = ['white',
                  'yellowtint',
                  'peachtint',
                  'pinktint',
                  'lilactint',
                  'bluetint',
                  'greentint']
  match = False
  while not match:
    if index > 6:
      index = index - 6
    else:
      match = True
  return chain_colors[index]

def get_ions(ion_list):
  ion_txt = "@spherelist {het M} color= gray  radius= 0.5 nobutton master= {hets}\n"
  ion_txt += ion_list
  return ion_txt

def get_kin_lots(chain, bond_hash, i_seq_name_hash, pdbID=None, index=0, show_hydrogen=True):
  mc_atoms = ["N", "CA", "C", "O", "OXT",
              "P", "OP1", "OP2", "OP3", "O5'", "C5'", "C4'", "O4'", "C1'",
              "C3'", "O3'", "C2'", "O2'"]
  mc_veclist = ""
  sc_veclist = ""
  mc_h_veclist = ""
  sc_h_veclist = ""
  ca_trace = ""
  virtual_bb = ""
  water_list = ""
  ion_list = ""
  kin_out = ""
  color = get_chain_color(index)
  mc_veclist = "@vectorlist {mc} color= %s  master= {mainchain}\n" % color
  sc_veclist = "@vectorlist {sc} color= cyan  master= {sidechain}\n"
  ca_trace = "@vectorlist {Calphas} color= %s master= {Calphas}\n" % color
  virtual_bb = "@vectorlist {Virtual BB} color= %s  off   master= {Virtual BB}\n" % color
  water_list = "@balllist {water O} color= peachtint  radius= 0.15  master= {water}\n"
  hets = "@vectorlist {het} color= pink  master= {hets}\n"
  het_h = "@vectorlist {ht H} color= gray  nobutton master= {hets} master= {H's}\n"
  if show_hydrogen:
    mc_h_veclist = \
      "@vectorlist {mc H} color= gray nobutton master= {mainchain} master= {H's}\n"
    sc_h_veclist = \
      "@vectorlist {sc H} color= gray nobutton master= {sidechain} master= {H's}\n"
  prev_resid = None
  cur_resid = None
  prev_C_xyz = {}
  prev_C_key = {}
  prev_CA_xyz = {}
  prev_CA_key = {}
  prev_O3_xyz = {}
  prev_O3_key = {}
  p_hash_key = {}
  p_hash_xyz = {}
  c1_hash_key = {}
  c1_hash_xyz = {}
  c4_hash_key = {}
  c4_hash_xyz = {}
  drawn_bonds = []
  for residue_group in chain.residue_groups():
    altloc_hash = {}
    iseq_altloc = {}
    cur_C_xyz = {}
    cur_C_key = {}
    cur_CA_xyz = {}
    cur_CA_key = {}
    cur_O3_xyz = {}
    cur_O3_key = {}
    for atom_group in residue_group.atom_groups():
      altloc = atom_group.altloc
      for atom in atom_group.atoms():
        if altloc_hash.get(atom.name.strip()) is None:
          altloc_hash[atom.name.strip()] = []
        altloc_hash[atom.name.strip()].append(altloc)
        iseq_altloc[atom.i_seq] = altloc
    cur_resid = residue_group.resid()
    for conformer in residue_group.conformers():
      for residue in conformer.residues():
        cur_resid = residue.resid()
        key_hash = {}
        xyz_hash = {}
        het_hash = {}
        altloc = conformer.altloc
        if altloc == '':
          altloc = ' '
        for atom in residue.atoms():
          cur_altlocs = altloc_hash.get(atom.name.strip())
          if cur_altlocs == ['']:
            cur_altloc = ' '
          elif altloc in cur_altlocs:
            cur_altloc = altloc
          else:
            # TO_DO: handle branching from altlocs
            cur_altloc == ' '
          key = "%s%s%s %s%s  B%.2f %s" % (
                atom.name.lower(),
                cur_altloc.lower(),
                residue.resname.lower(),
                chain.id,
                residue_group.resid(),
                atom.b,
                pdbID)
          key_hash[atom.name.strip()] = key
          xyz_hash[atom.name.strip()] = atom.xyz
          if(common_residue_names_get_class(residue.resname) == "common_amino_acid"):
            if atom.name == ' C  ':
              cur_C_xyz[altloc] = atom.xyz
              cur_C_key[altloc] = key
            if atom.name == ' CA ':
              cur_CA_xyz[altloc] = atom.xyz
              cur_CA_key[altloc] = key
              if len(prev_CA_key) > 0 and len(prev_CA_xyz) > 0:
                if int(residue_group.resseq_as_int()) - int(prev_resid[0:4]) == 1:
                  try:
                    prev_key = prev_CA_key.get(altloc)
                    prev_xyz = prev_CA_xyz.get(altloc)
                    if prev_key is None:
                      prev_key = prev_CA_key.get(' ')
                      prev_xyz = prev_CA_xyz.get(' ')
                    if prev_key is None:
                      continue
                    ca_trace += kin_vec(prev_key, prev_xyz, key, atom.xyz)
                  except Exception:
                    pass
            if atom.name == ' N  ':
              if len(prev_C_key) > 0 and len(prev_C_xyz) > 0:
                if int(residue_group.resseq_as_int()) - int(prev_resid[0:4]) == 1:
                  try:
                    prev_key = prev_C_key.get(altloc)
                    prev_xyz = prev_C_xyz.get(altloc)
                    if prev_key is None:
                      prev_key = prev_C_key.get(' ')
                      prev_xyz = prev_C_xyz.get(' ')
                    if prev_key is None:
                      continue
                    mc_veclist += kin_vec(prev_key, prev_xyz, key, atom.xyz)
                  except Exception:
                    pass
          elif(common_residue_names_get_class(residue.resname) == "common_rna_dna"):
            if atom.name == " O3'":
              cur_O3_xyz[altloc] = atom.xyz
              cur_O3_key[altloc] = key
            elif atom.name == ' P  ':
              if len(prev_O3_key) > 0 and len(prev_O3_xyz) > 0:
                if int(residue_group.resseq_as_int()) - int(prev_resid[0:4]) == 1:
                  try:
                    prev_key = prev_O3_key.get(altloc)
                    prev_xyz = prev_O3_xyz.get(altloc)
                    if prev_key is None:
                      prev_key = prev_O3_key.get(' ')
                      prev_xyz = prev_O3_xyz.get(' ')
                    if prev_key is None:
                      continue
                    mc_veclist += kin_vec(prev_key, prev_xyz, key, atom.xyz)
                  except Exception:
                    pass
              p_hash_key[residue_group.resseq_as_int()] = key
              p_hash_xyz[residue_group.resseq_as_int()] = atom.xyz
            elif atom.name == " C1'":
              c1_hash_key[residue_group.resseq_as_int()] = key
              c1_hash_xyz[residue_group.resseq_as_int()] = atom.xyz
            elif atom.name == " C4'":
              c4_hash_key[residue_group.resseq_as_int()] = key
              c4_hash_xyz[residue_group.resseq_as_int()] = atom.xyz
          elif(common_residue_names_get_class(residue.resname) == "common_element"):
            ion_list += "{%s} %.3f %.3f %.3f\n" % (
              key,
              atom.xyz[0],
              atom.xyz[1],
              atom.xyz[2])
          elif( (common_residue_names_get_class(residue.resname) == "other") and
                (len(residue.atoms())==1) ):
            ion_list += "{%s} %.3f %.3f %.3f\n" % (
              key,
              atom.xyz[0],
              atom.xyz[1],
              atom.xyz[2])
          elif residue.resname.lower() == 'hoh':
            if atom.name == ' O  ':
              water_list += "{%s} P %.3f %.3f %.3f\n" % (
                key,
                atom.xyz[0],
                atom.xyz[1],
                atom.xyz[2])
          else:
            het_hash[atom.name.strip()] = [key, atom.xyz]

        if(common_residue_names_get_class(residue.resname) == "common_rna_dna"):
          try:
            virtual_bb += kin_vec(c4_hash_key[residue_group.resseq_as_int()-1],
                                  c4_hash_xyz[residue_group.resseq_as_int()-1],
                                  p_hash_key[residue_group.resseq_as_int()],
                                  p_hash_xyz[residue_group.resseq_as_int()])
          except Exception:
            pass
          try:
            virtual_bb += kin_vec(p_hash_key[residue_group.resseq_as_int()],
                                  p_hash_xyz[residue_group.resseq_as_int()],
                                  c4_hash_key[residue_group.resseq_as_int()],
                                  c4_hash_xyz[residue_group.resseq_as_int()])
          except Exception:
            pass
          try:
            virtual_bb += kin_vec(c4_hash_key[residue_group.resseq_as_int()],
                                  c4_hash_xyz[residue_group.resseq_as_int()],
                                  c1_hash_key[residue_group.resseq_as_int()],
                                  c1_hash_xyz[residue_group.resseq_as_int()])
          except Exception:
            pass

        cur_i_seqs = []
        for atom in residue.atoms():
          cur_i_seqs.append(atom.i_seq)

        for atom in residue.atoms():
          try:
            cur_bonds = bond_hash[atom.i_seq]
          except Exception:
            continue
          for bond in cur_bonds:
            atom_1 = i_seq_name_hash.get(atom.i_seq)
            if atom_1 is not None:
              atom_1 = atom_1[0:4].strip()
            atom_2 = i_seq_name_hash.get(bond)
            if atom_2 is not None:
              atom_2 = atom_2[0:4].strip()
            if atom_1 is None or atom_2 is None:
              continue
            # handle altlocs ########
            drawn_key = key_hash[atom_1]+key_hash[atom_2]
            if drawn_key in drawn_bonds:
              continue
            altloc_2 = iseq_altloc.get(bond)
            if altloc_2 != altloc and altloc_2 != '':
              continue
            #########################
            if (common_residue_names_get_class(residue.resname) == 'other' or \
                common_residue_names_get_class(residue.resname) == 'common_small_molecule'):
              if atom_1.startswith('H') or atom_2.startswith('H') or \
                 atom_1.startswith('D') or atom_2.startswith('D'):
                if show_hydrogen:
                  try:
                    het_h += kin_vec(het_hash[atom_1][0],
                                     het_hash[atom_1][1],
                                     het_hash[atom_2][0],
                                     het_hash[atom_2][1])
                  except Exception:
                    pass
              else:
                try:
                  hets += kin_vec(het_hash[atom_1][0],
                                  het_hash[atom_1][1],
                                  het_hash[atom_2][0],
                                  het_hash[atom_2][1])
                except Exception:
                  pass
            elif common_residue_names_get_class(residue.resname) == "common_amino_acid" or \
                 common_residue_names_get_class(residue.resname) == "common_rna_dna":
              if atom_1 in mc_atoms and atom_2 in mc_atoms:
                try:
                   if atom_1 == "C" and atom_2 == "N":
                     pass
                   elif atom_1 == "O3'" and atom_2 == "P":
                     pass
                   else:
                     mc_veclist += kin_vec(key_hash[atom_1],
                                           xyz_hash[atom_1],
                                           key_hash[atom_2],
                                           xyz_hash[atom_2])
                except Exception:
                  pass
              elif atom_1.startswith('H') or atom_2.startswith('H') or \
                   atom_1.startswith('D') or atom_2.startswith('D'):
                if show_hydrogen:
                  if (atom_1 in mc_atoms or atom_2 in mc_atoms):
                    try:
                      mc_h_veclist += kin_vec(key_hash[atom_1],
                                              xyz_hash[atom_1],
                                              key_hash[atom_2],
                                              xyz_hash[atom_2])
                    except Exception:
                      pass
                  else:
                    try:
                      sc_h_veclist += kin_vec(key_hash[atom_1],
                                              xyz_hash[atom_1],
                                              key_hash[atom_2],
                                              xyz_hash[atom_2])
                    except Exception:
                      pass
              else:
                try:
                  sc_veclist += kin_vec(key_hash[atom_1],
                                        xyz_hash[atom_1],
                                        key_hash[atom_2],
                                        xyz_hash[atom_2])
                except Exception:
                  pass
              drawn_bonds.append(drawn_key)
    prev_CA_xyz = cur_CA_xyz
    prev_CA_key = cur_CA_key
    prev_C_xyz = cur_C_xyz
    prev_C_key = cur_C_key
    prev_resid = cur_resid
    prev_O3_key = cur_O3_key
    prev_O3_xyz = cur_O3_xyz

  ion_kin = None
  if len(ion_list) > 1:
    ion_kin = get_ions(ion_list)

  #clean up empty lists:
  if len(mc_veclist.splitlines()) > 1:
    kin_out += mc_veclist
  if len(mc_h_veclist.splitlines()) > 1:
    kin_out += mc_h_veclist
  if len(ca_trace.splitlines()) > 1:
    kin_out += ca_trace
  if len(sc_veclist.splitlines()) > 1:
    kin_out += sc_veclist
  if len(sc_h_veclist.splitlines()) > 1:
    kin_out += sc_h_veclist
  if len(water_list.splitlines()) > 1:
    kin_out += water_list
  if len(virtual_bb.splitlines()) > 1:
    kin_out += virtual_bb
  if len(hets.splitlines()) > 1:
    kin_out += hets
  if ion_kin is not None:
    kin_out += ion_kin
  if len(het_h.splitlines()) > 1:
    kin_out += het_h
  return kin_out

def get_default_header():
  header = """
@kinemage 1
@onewidth
@1viewid {Overview}
@master {mainchain} indent
@master {Calphas} indent
@master {sidechain} indent
@master {H's} indent
@pointmaster 'H' {H's}
@master {water} indent
"""
  return header

def get_footer():
  footer = """
@master {mainchain} off
@master {sidechain} off
@master {H's} off
@master {water} off
@master {Rota outliers} on
@master {Rama outliers} on
@master {Calphas} on
@master {Virtual BB} on
@master {vdw contact} off
@master {small overlap} off
@master {H-bonds} off
@master {length dev} on
@master {angle dev} on
@master {length dev} on
@master {Cbeta dev} on
@master {base-P perp} on
@master {hets} on
"""
  return footer

def get_altid_controls(hierarchy):
  #print hierarchy.get_conformer_indices()
  #STOP()
  altids = []
  altid_controls = ""
  txt = "@pointmaster 'a' {alta} on"
  for model in hierarchy.models():
    for chain in model.chains():
      for conformer in chain.conformers():
        altloc = conformer.altloc
        if altloc not in altids and altloc != '':
          altids.append(altloc)
  for i, altid in enumerate(altids):
    altid_controls += "@pointmaster '%s' {alt%s} " % (altid.lower(),
                                                      altid.lower())
    if i == 0:
      altid_controls += "on\n"
    else:
      altid_controls += "off\n"
  return altid_controls

def make_multikin(f, processed_pdb_file, pdbID=None, keep_hydrogens=False):
  if pdbID == None:
    pdbID = "PDB"
  hierarchy = processed_pdb_file.all_chain_proxies.pdb_hierarchy
  i_seq_name_hash = build_name_hash(pdb_hierarchy=hierarchy)
  sites_cart=processed_pdb_file.all_chain_proxies.sites_cart
  geometry = processed_pdb_file.geometry_restraints_manager()
  flags = geometry_restraints.flags.flags(default=True)
  angle_proxies = geometry.angle_proxies
  pair_proxies = geometry.pair_proxies(flags=flags,
                                       sites_cart=sites_cart)
  bond_proxies = pair_proxies.bond_proxies
  quick_bond_hash = {}
  for bp in bond_proxies.simple:
    if (i_seq_name_hash[bp.i_seqs[0]][9:14] ==
        i_seq_name_hash[bp.i_seqs[1]][9:14]):
      if quick_bond_hash.get(bp.i_seqs[0]) is None:
        quick_bond_hash[bp.i_seqs[0]] = []
      quick_bond_hash[bp.i_seqs[0]].append(bp.i_seqs[1])
  kin_out = get_default_header()
  altid_controls = get_altid_controls(hierarchy=hierarchy)
  if altid_controls != "":
    kin_out += altid_controls
  kin_out += "@group {%s} dominant animate\n" % pdbID
  initiated_chains = []
  rot_outliers = rotalyze(pdb_hierarchy=hierarchy, outliers_only=True)
  cb = cbetadev(
    pdb_hierarchy=hierarchy,
    outliers_only=True)
  rama = ramalyze(pdb_hierarchy=hierarchy, outliers_only=True)
  counter = 0
  for model in hierarchy.models():
    for chain in model.chains():
      if chain.id not in initiated_chains:
        kin_out += "@subgroup {%s} dominant master= {chain %s}\n" % (
                  pdbID,
                  chain.id)
        initiated_chains.append(chain.id)
      kin_out += get_kin_lots(chain=chain,
                              bond_hash=quick_bond_hash,
                              i_seq_name_hash=i_seq_name_hash,
                              pdbID=pdbID,
                              index=counter)
      if (chain.is_protein()) :
        kin_out += rotamer_outliers(chain=chain, pdbID=pdbID,
          rot_outliers=rot_outliers)
        kin_out += rama_outliers(chain=chain, pdbID=pdbID, ram_outliers=rama)
      # TODO use central methods in mmtbx.validation.restraints
      kin_out += get_angle_outliers(angle_proxies=angle_proxies,
                                    chain=chain,
                                    sites_cart=sites_cart,
                                    hierarchy=hierarchy)
      kin_out += get_bond_outliers(bond_proxies=bond_proxies,
                                   chain=chain,
                                   sites_cart=sites_cart,
                                   hierarchy=hierarchy)
      if (chain.is_protein()) :
        kin_out += cbeta_dev(chain_id=chain.id,
          outliers=cb.results)
      kin_out += pperp_outliers(hierarchy=hierarchy,
                                chain=chain)
      counter += 1
  kin_out += make_probe_dots(hierarchy=hierarchy, keep_hydrogens=keep_hydrogens)
  kin_out += get_footer()

  outfile = file(f, 'w')
  for line in kin_out:
    outfile.write(line)
  outfile.close()
  return f

def usage():
  return """
phenix.kinemage file.pdb [params.eff] [options ...]

Options:

  pdb=input_file        input PDB file
  cif=cif_file          input custom definitions (ligands, etc.)
  keep_hydrogens=False  keep input hydrogen files (otherwise regenerate)

Example:

  phenix.kinemage pdb=1ubq.pdb cif=ligands.cif
"""

def run(args):
  if (len(args) == 0 or "--help" in args or "--h" in args or "-h" in args):
      raise Usage(usage())
  pdbID = None
  master_phil = get_master_phil()
  import iotbx.utils
  input_objects = iotbx.utils.process_command_line_inputs(
    args=args,
    master_phil=master_phil,
    input_types=("pdb", "cif"))
  work_phil = master_phil.fetch(sources=input_objects["phil"])
  work_params = work_phil.extract()
  if work_params.kinemage.pdb == None:
    assert len(input_objects["pdb"]) == 1
    file_obj = input_objects["pdb"][0]
    file_name = file_obj.file_name
  else:
    file_name = work_params.kinemage.pdb
  if file_name and os.path.exists(file_name):
    pdb_io = pdb.input(file_name)
    pdbID = os.path.basename(pdb_io.source_info().split(' ')[1]).split('.')[0]
  else :
    raise Sorry("PDB file does not exist")
  assert pdb_io is not None
  cif_file = None
  cif_object = None
  if len(work_params.kinemage.cif) == 0:
    if len(input_objects["cif"]) > 0:
      cif_file = []
      for cif in input_objects["cif"]:
        cif_file.append(cif.file_name)
  else:
    cif_file = work_params.kinemage.cif
  mon_lib_srv = monomer_library.server.server()
  ener_lib = monomer_library.server.ener_lib()
  if cif_file != None:
    for cif in cif_file:
      try:
        cif_object = monomer_library.server.read_cif(file_name=cif)
      except Exception:
        raise Sorry("Unknown file format: %s" % show_string(cif))
    if cif_object != None:
      for srv in [mon_lib_srv, ener_lib]:
        srv.process_cif_object(cif_object=cif_object)
  processed_pdb_file = pdb_interpretation.process(
        mon_lib_srv=mon_lib_srv,
        ener_lib=ener_lib,
        pdb_inp=pdb_io,
        for_dihedral_reference=True,
        substitute_non_crystallographic_unit_cell_if_necessary=True)
  if work_params.kinemage.out_file is not None:
    outfile = work_params.kinemage.out_file
  else :
    outfile = pdbID+'.kin'
  outfile = make_multikin(f=outfile,
                          processed_pdb_file=processed_pdb_file,
                          pdbID=pdbID,
                          keep_hydrogens=work_params.kinemage.keep_hydrogens)
  return outfile
