# coding: utf-8
# Copyright (c) Pymatgen Development Team.
# Distributed under the terms of the MIT License.


import re
import os
import warnings
from string import Template

import numpy as np

from monty.io import zopen

from pymatgen.core.structure import Molecule, Structure
from monty.json import MSONable
from pymatgen.core.units import Energy
from pymatgen.core.units import FloatWithUnit
from pymatgen.analysis.excitation import ExcitationSpectrum

"""
This module implements input and output processing from Nwchem.

2015/09/21 - Xin Chen (chenxin13@mails.tsinghua.edu.cn):

    NwOutput will read new kinds of data:
        1. normal hessian matrix.       ["hessian"]
        2. projected hessian matrix.    ["projected_hessian"]
        3. normal frequencies.          ["normal_frequencies"]

    For backward compatibility, the key for accessing the projected frequencies
    is still 'frequencies'.

2015/10/12 - Xin Chen
    NwOutput will read new kinds of data:
        1. forces.                      ["forces"]

"""

__author__ = "Shyue Ping Ong"
__copyright__ = "Copyright 2012, The Materials Project"
__version__ = "0.1"
__maintainer__ = "Shyue Ping Ong"
__email__ = "shyuep@gmail.com"
__date__ = "6/5/13"


NWCHEM_BASIS_LIBRARY = None
if os.environ.get("NWCHEM_BASIS_LIBRARY"):
    NWCHEM_BASIS_LIBRARY = set(os.listdir(os.environ["NWCHEM_BASIS_LIBRARY"]))


class NwTask(MSONable):
    """
    Base task for Nwchem.
    """

    theories = {"g3gn": "some description",
                "scf": "Hartree-Fock",
                "dft": "DFT",
                "esp": "ESP",
                "sodft": "Spin-Orbit DFT",
                "mp2": "MP2 using a semi-direct algorithm",
                "direct_mp2": "MP2 using a full-direct algorithm",
                "rimp2": "MP2 using the RI approximation",
                "ccsd": "Coupled-cluster single and double excitations",
                "ccsd(t)": "Coupled-cluster linearized triples approximation",
                "ccsd+t(ccsd)": "Fourth order triples contribution",
                "mcscf": "Multiconfiguration SCF",
                "selci": "Selected CI with perturbation correction",
                "md": "Classical molecular dynamics simulation",
                "pspw": "Pseudopotential plane-wave DFT for molecules and "
                        "insulating solids using NWPW",
                "band": "Pseudopotential plane-wave DFT for solids using NWPW",
                "tce": "Tensor Contraction Engine",
                "tddft": "Time Dependent DFT"}

    operations = {"energy": "Evaluate the single point energy.",
                  "gradient": "Evaluate the derivative of the energy with "
                              "respect to nuclear coordinates.",
                  "optimize": "Minimize the energy by varying the molecular "
                              "structure.",
                  "saddle": "Conduct a search for a transition state (or "
                            "saddle point).",
                  "hessian": "Compute second derivatives.",
                  "frequencies": "Compute second derivatives and print out an "
                                 "analysis of molecular vibrations.",
                  "freq": "Same as frequencies.",
                  "vscf": "Compute anharmonic contributions to the "
                          "vibrational modes.",
                  "property": "Calculate the properties for the wave "
                              "function.",
                  "dynamics": "Perform classical molecular dynamics.",
                  "thermodynamics": "Perform multi-configuration "
                                    "thermodynamic integration using "
                                    "classical MD.",
                  "": "dummy"}

    def __init__(self, charge, spin_multiplicity, basis_set,
                 basis_set_option="cartesian",
                 title=None, theory="dft", operation="optimize",
                 theory_directives=None, alternate_directives=None):
        """
        Very flexible arguments to support many types of potential setups.
        Users should use more friendly static methods unless they need the
        flexibility.

        Args:
            charge: Charge of the molecule. If None, charge on molecule is
                used. Defaults to None. This allows the input file to be set a
                charge independently from the molecule itself.
            spin_multiplicity: Spin multiplicity of molecule. Defaults to None,
                which means that the spin multiplicity is set to 1 if the
                molecule has no unpaired electrons and to 2 if there are
                unpaired electrons.
            basis_set: The basis set used for the task as a dict. E.g.,
                {"C": "6-311++G**", "H": "6-31++G**"}.
            basis_set_option: cartesian (default) | spherical,
            title: Title for the task. Defaults to None, which means a title
                based on the theory and operation of the task is
                autogenerated.
            theory: The theory used for the task. Defaults to "dft".
            operation: The operation for the task. Defaults to "optimize".
            theory_directives: A dict of theory directives. For example,
                if you are running dft calculations, you may specify the
                exchange correlation functional using {"xc": "b3lyp"}.
            alternate_directives: A dict of alternate directives. For
                example, to perform cosmo calculations and dielectric
                constant of 78, you'd supply {'cosmo': {"dielectric": 78}}.
        """
        # Basic checks.
        if theory.lower() not in NwTask.theories.keys():
            raise NwInputError("Invalid theory {}".format(theory))

        if operation.lower() not in NwTask.operations.keys():
            raise NwInputError("Invalid operation {}".format(operation))
        self.charge = charge
        self.spin_multiplicity = spin_multiplicity
        self.title = title if title is not None else "{} {}".format(theory,
                                                                    operation)
        self.theory = theory

        self.basis_set = basis_set or {}
        if NWCHEM_BASIS_LIBRARY is not None:
            for b in set(self.basis_set.values()):
                if re.sub(r'\*', "s", b.lower()) not in NWCHEM_BASIS_LIBRARY:
                    warnings.warn(
                        "Basis set %s not in in NWCHEM_BASIS_LIBRARY" % b)

        self.basis_set_option = basis_set_option

        self.operation = operation
        self.theory_directives = theory_directives or {}
        self.alternate_directives = alternate_directives or {}

    def __str__(self):
        bset_spec = []
        for el, bset in sorted(self.basis_set.items(), key=lambda x: x[0]):
            bset_spec.append(" {} library \"{}\"".format(el, bset))
        theory_spec = []
        if self.theory_directives:
            theory_spec.append("{}".format(self.theory))
            for k in sorted(self.theory_directives.keys()):
                theory_spec.append(" {} {}".format(k, self.theory_directives[
                    k]))
            theory_spec.append("end")
        for k in sorted(self.alternate_directives.keys()):
            theory_spec.append(k)
            for k2 in sorted(self.alternate_directives[k].keys()):
                theory_spec.append(" {} {}".format(
                    k2, self.alternate_directives[k][k2]))
            theory_spec.append("end")

        t = Template("""title "$title"
charge $charge
basis $basis_set_option
$bset_spec
end
$theory_spec
""")

        output = t.substitute(
            title=self.title, charge=self.charge,
            spinmult=self.spin_multiplicity,
            basis_set_option=self.basis_set_option,
            bset_spec="\n".join(bset_spec),
            theory_spec="\n".join(theory_spec),
            theory=self.theory)

        if self.operation is not None:
            output += "task %s %s" % (self.theory, self.operation)
        return output

    def as_dict(self):
        return {"@module": self.__class__.__module__,
                "@class": self.__class__.__name__,
                "charge": self.charge,
                "spin_multiplicity": self.spin_multiplicity,
                "title": self.title, "theory": self.theory,
                "operation": self.operation, "basis_set": self.basis_set,
                "basis_set_option": self.basis_set_option,
                "theory_directives": self.theory_directives,
                "alternate_directives": self.alternate_directives}

    @classmethod
    def from_dict(cls, d):
        return NwTask(charge=d["charge"],
                      spin_multiplicity=d["spin_multiplicity"],
                      title=d["title"], theory=d["theory"],
                      operation=d["operation"], basis_set=d["basis_set"],
                      basis_set_option=d['basis_set_option'],
                      theory_directives=d["theory_directives"],
                      alternate_directives=d["alternate_directives"])

    @classmethod
    def from_molecule(cls, mol, theory, charge=None, spin_multiplicity=None,
                      basis_set="6-31g", basis_set_option="cartesian",
                      title=None, operation="optimize", theory_directives=None,
                      alternate_directives=None):
        """
        Very flexible arguments to support many types of potential setups.
        Users should use more friendly static methods unless they need the
        flexibility.

        Args:
            mol: Input molecule
            charge: Charge of the molecule. If None, charge on molecule is
                used. Defaults to None. This allows the input file to be set a
                charge independently from the molecule itself.
            spin_multiplicity: Spin multiplicity of molecule. Defaults to None,
                which means that the spin multiplicity is set to 1 if the
                molecule has no unpaired electrons and to 2 if there are
                unpaired electrons.
            basis_set: The basis set to be used as string or a dict. E.g.,
                {"C": "6-311++G**", "H": "6-31++G**"} or "6-31G". If string,
                same basis set is used for all elements.
            basis_set_option: cartesian (default) | spherical,
            title: Title for the task. Defaults to None, which means a title
                based on the theory and operation of the task is
                autogenerated.
            theory: The theory used for the task. Defaults to "dft".
            operation: The operation for the task. Defaults to "optimize".
            theory_directives: A dict of theory directives. For example,
                if you are running dft calculations, you may specify the
                exchange correlation functional using {"xc": "b3lyp"}.
            alternate_directives: A dict of alternate directives. For
                example, to perform cosmo calculations with DFT, you'd supply
                {'cosmo': "cosmo"}.
        """
        title = title if title is not None else "{} {} {}".format(
            re.sub(r"\s", "", mol.formula), theory, operation)

        charge = charge if charge is not None else mol.charge
        nelectrons = - charge + mol.charge + mol.nelectrons
        if spin_multiplicity is not None:
            spin_multiplicity = spin_multiplicity
            if (nelectrons + spin_multiplicity) % 2 != 1:
                raise ValueError(
                    "Charge of {} and spin multiplicity of {} is"
                    " not possible for this molecule".format(
                        charge, spin_multiplicity))
        elif charge == mol.charge:
            spin_multiplicity = mol.spin_multiplicity
        else:
            spin_multiplicity = 1 if nelectrons % 2 == 0 else 2

        elements = set(mol.composition.get_el_amt_dict().keys())
        if isinstance(basis_set, str):
            basis_set = {el: basis_set for el in elements}

        basis_set_option = basis_set_option

        return NwTask(charge, spin_multiplicity, basis_set,
                      basis_set_option=basis_set_option,
                      title=title, theory=theory, operation=operation,
                      theory_directives=theory_directives,
                      alternate_directives=alternate_directives)

    @classmethod
    def dft_task(cls, mol, xc="b3lyp", **kwargs):
        """
        A class method for quickly creating DFT tasks with optional
        cosmo parameter .

        Args:
            mol: Input molecule
            xc: Exchange correlation to use.
            \\*\\*kwargs: Any of the other kwargs supported by NwTask. Note the
                theory is always "dft" for a dft task.
        """
        t = NwTask.from_molecule(mol, theory="dft", **kwargs)
        t.theory_directives.update({"xc": xc,
                                    "mult": t.spin_multiplicity})
        return t

    @classmethod
    def esp_task(cls, mol, **kwargs):
        """
        A class method for quickly creating ESP tasks with RESP
        charge fitting.

        Args:
            mol: Input molecule
            \\*\\*kwargs: Any of the other kwargs supported by NwTask. Note the
                theory is always "dft" for a dft task.
        """
        return NwTask.from_molecule(mol, theory="esp", **kwargs)


class NwInput(MSONable):
    """
    An object representing a Nwchem input file, which is essentially a list
    of tasks on a particular molecule.

    Args:
        mol: Input molecule. If molecule is a single string, it is used as a
            direct input to the geometry section of the Gaussian input
            file.
        tasks: List of NwTasks.
        directives: List of root level directives as tuple. E.g.,
            [("start", "water"), ("print", "high")]
        geometry_options: Additional list of options to be supplied to the
            geometry. E.g., ["units", "angstroms", "noautoz"]. Defaults to
            ("units", "angstroms").
        symmetry_options: Addition list of option to be supplied to the
            symmetry. E.g. ["c1"] to turn off the symmetry
        memory_options: Memory controlling options. str.
            E.g "total 1000 mb stack 400 mb"
    """

    def __init__(self, mol, tasks, directives=None,
                 geometry_options=("units", "angstroms"),
                 symmetry_options=None,
                 memory_options=None):
        self._mol = mol
        self.directives = directives if directives is not None else []
        self.tasks = tasks
        self.geometry_options = geometry_options
        self.symmetry_options = symmetry_options
        self.memory_options = memory_options

    @property
    def molecule(self):
        """
        Returns molecule associated with this GaussianInput.
        """
        return self._mol

    def __str__(self):
        o = []
        if self.memory_options:
            o.append('memory ' + self.memory_options)
        for d in self.directives:
            o.append("{} {}".format(d[0], d[1]))
        o.append("geometry "
                 + " ".join(self.geometry_options))
        if self.symmetry_options:
            o.append(" symmetry " + " ".join(self.symmetry_options))
        for site in self._mol:
            o.append(" {} {} {} {}".format(site.specie.symbol, site.x, site.y,
                                           site.z))
        o.append("end\n")
        for t in self.tasks:
            o.append(str(t))
            o.append("")
        return "\n".join(o)

    def write_file(self, filename):
        with zopen(filename, "w") as f:
            f.write(self.__str__())

    def as_dict(self):
        return {
            "mol": self._mol.as_dict(),
            "tasks": [t.as_dict() for t in self.tasks],
            "directives": [list(t) for t in self.directives],
            "geometry_options": list(self.geometry_options),
            "symmetry_options": self.symmetry_options,
            "memory_options": self.memory_options
        }

    @classmethod
    def from_dict(cls, d):
        return NwInput(Molecule.from_dict(d["mol"]),
                       tasks=[NwTask.from_dict(dt) for dt in d["tasks"]],
                       directives=[tuple(li) for li in d["directives"]],
                       geometry_options=d["geometry_options"],
                       symmetry_options=d["symmetry_options"],
                       memory_options=d["memory_options"])

    @classmethod
    def from_string(cls, string_input):
        """
        Read an NwInput from a string. Currently tested to work with
        files generated from this class itself.

        Args:
            string_input: string_input to parse.

        Returns:
            NwInput object
        """
        directives = []
        tasks = []
        charge = None
        spin_multiplicity = None
        title = None
        basis_set = None
        basis_set_option = None
        theory_directives = {}
        geom_options = None
        symmetry_options = None
        memory_options = None
        lines = string_input.strip().split("\n")
        while len(lines) > 0:
            l = lines.pop(0).strip()
            if l == "":
                continue

            toks = l.split()
            if toks[0].lower() == "geometry":
                geom_options = toks[1:]
                l = lines.pop(0).strip()
                toks = l.split()
                if toks[0].lower() == "symmetry":
                    symmetry_options = toks[1:]
                    l = lines.pop(0).strip()
                # Parse geometry
                species = []
                coords = []
                while l.lower() != "end":
                    toks = l.split()
                    species.append(toks[0])
                    coords.append([float(i) for i in toks[1:]])
                    l = lines.pop(0).strip()
                mol = Molecule(species, coords)
            elif toks[0].lower() == "charge":
                charge = int(toks[1])
            elif toks[0].lower() == "title":
                title = l[5:].strip().strip("\"")
            elif toks[0].lower() == "basis":
                # Parse basis sets
                l = lines.pop(0).strip()
                basis_set = {}
                while l.lower() != "end":
                    toks = l.split()
                    basis_set[toks[0]] = toks[-1].strip("\"")
                    l = lines.pop(0).strip()
            elif toks[0].lower() in NwTask.theories:
                # read the basis_set_option
                if len(toks) > 1:
                    basis_set_option = toks[1]
                # Parse theory directives.
                theory = toks[0].lower()
                l = lines.pop(0).strip()
                theory_directives[theory] = {}
                while l.lower() != "end":
                    toks = l.split()
                    theory_directives[theory][toks[0]] = toks[-1]
                    if toks[0] == "mult":
                        spin_multiplicity = float(toks[1])
                    l = lines.pop(0).strip()
            elif toks[0].lower() == "task":
                tasks.append(
                    NwTask(charge=charge,
                           spin_multiplicity=spin_multiplicity,
                           title=title, theory=toks[1],
                           operation=toks[2], basis_set=basis_set,
                           basis_set_option=basis_set_option,
                           theory_directives=theory_directives.get(toks[1])))
            elif toks[0].lower() == "memory":
                    memory_options = ' '.join(toks[1:])
            else:
                directives.append(l.strip().split())

        return NwInput(mol, tasks=tasks, directives=directives,
                       geometry_options=geom_options,
                       symmetry_options=symmetry_options,
                       memory_options=memory_options)

    @classmethod
    def from_file(cls, filename):
        """
        Read an NwInput from a file. Currently tested to work with
        files generated from this class itself.

        Args:
            filename: Filename to parse.

        Returns:
            NwInput object
        """
        with zopen(filename) as f:
            return cls.from_string(f.read())


class NwInputError(Exception):
    """
    Error class for NwInput.
    """
    pass


class NwOutput:
    """
    A Nwchem output file parser. Very basic for now - supports only dft and
    only parses energies and geometries. Please note that Nwchem typically
    outputs energies in either au or kJ/mol. All energies are converted to
    eV in the parser.

    Args:
        filename: Filename to read.
    """

    def __init__(self, filename):
        self.filename = filename

        with zopen(filename) as f:
            data = f.read()

        chunks = re.split(r"NWChem Input Module", data)
        if re.search(r"CITATION", chunks[-1]):
            chunks.pop()
        preamble = chunks.pop(0)

        self.raw = data
        self.job_info = self._parse_preamble(preamble)
        self.data = [self._parse_job(c) for c in chunks]

    def parse_tddft(self):
        """
        Parses TDDFT roots. Adapted from nw_spectrum.py script.

        Returns:
            {
                "singlet": [
                    {
                        "energy": float,
                        "osc_strength: float
                    }
                ],
                "triplet": [
                    {
                        "energy": float
                    }
                ]
            }
        """
        start_tag = "Convergence criterion met"
        end_tag = "Excited state energy"
        singlet_tag = "singlet excited"
        triplet_tag = "triplet excited"
        state = "singlet"
        inside = False  # true when we are inside output block

        lines = self.raw.split("\n")

        roots = {"singlet": [], "triplet": []}

        while lines:
            line = lines.pop(0).strip()

            if start_tag in line:
                inside = True

            elif end_tag in line:
                inside = False

            elif singlet_tag in line:
                state = "singlet"

            elif triplet_tag in line:
                state = "triplet"

            elif inside and "Root" in line and "eV" in line:
                toks = line.split()
                roots[state].append({"energy": float(toks[-2])})

            elif inside and "Dipole Oscillator Strength" in line:
                osc = float(line.split()[-1])
                roots[state][-1]["osc_strength"] = osc

        return roots

    def get_excitation_spectrum(self, width=0.1, npoints=2000):
        """
        Generate an excitation spectra from the singlet roots of TDDFT
        calculations.

        Args:
            width (float): Width for Gaussian smearing.
            npoints (int): Number of energy points. More points => smoother
                curve.

        Returns:
            (ExcitationSpectrum) which can be plotted using
                pymatgen.vis.plotters.SpectrumPlotter.
        """
        roots = self.parse_tddft()
        data = roots["singlet"]
        en = np.array([d["energy"] for d in data])
        osc = np.array([d["osc_strength"] for d in data])

        epad = 20.0 * width
        emin = en[0] - epad
        emax = en[-1] + epad
        de = (emax - emin) / npoints

        # Use width of at least two grid points
        if width < 2 * de:
            width = 2 * de

        energies = [emin + ie * de for ie in range(npoints)]

        cutoff = 20.0 * width
        gamma = 0.5 * width
        gamma_sqrd = gamma * gamma

        de = (energies[-1] - energies[0]) / (len(energies) - 1)
        prefac = gamma / np.pi * de

        x = []
        y = []
        for energy in energies:
            xx0 = energy - en
            stot = osc / (xx0 * xx0 + gamma_sqrd)
            t = np.sum(stot[np.abs(xx0) <= cutoff])
            x.append(energy)
            y.append(t * prefac)
        return ExcitationSpectrum(x, y)

    def _parse_preamble(self, preamble):
        info = {}
        for l in preamble.split("\n"):
            toks = l.split("=")
            if len(toks) > 1:
                info[toks[0].strip()] = toks[-1].strip()
        return info

    def __iter__(self):
        return self.data.__iter__()

    def __getitem__(self, ind):
        return self.data[ind]

    def __len__(self):
        return len(self.data)

    def _parse_job(self, output):
        energy_patt = re.compile(r'Total \w+ energy\s+=\s+([.\-\d]+)')
        energy_gas_patt = re.compile(r'gas phase energy\s+=\s+([.\-\d]+)')
        energy_sol_patt = re.compile(r'sol phase energy\s+=\s+([.\-\d]+)')
        coord_patt = re.compile(r'\d+\s+(\w+)\s+[.\-\d]+\s+([.\-\d]+)\s+'
                                r'([.\-\d]+)\s+([.\-\d]+)')
        lat_vector_patt = re.compile(r'a[123]=<\s+([.\-\d]+)\s+'
                                     r'([.\-\d]+)\s+([.\-\d]+)\s+>')
        corrections_patt = re.compile(r'([\w\-]+ correction to \w+)\s+='
                                      r'\s+([.\-\d]+)')
        preamble_patt = re.compile(r'(No. of atoms|No. of electrons'
                                   r'|SCF calculation type|Charge|Spin '
                                   r'multiplicity)\s*:\s*(\S+)')
        force_patt = re.compile(r'\s+(\d+)\s+(\w+)' + 6 * r'\s+([0-9\.\-]+)')

        time_patt = re.compile(
            r'\s+ Task \s+ times \s+ cpu: \s+   ([.\d]+)s .+ ', re.VERBOSE)

        error_defs = {
            "calculations not reaching convergence": "Bad convergence",
            "Calculation failed to converge": "Bad convergence",
            "geom_binvr: #indep variables incorrect": "autoz error",
            "dft optimize failed": "Geometry optimization failed"}

        fort2py = lambda x: x.replace("D", "e")
        isfloatstring = lambda s: s.find(".") == -1

        parse_hess = False
        parse_proj_hess = False
        hessian = None
        projected_hessian = None
        parse_force = False
        all_forces = []
        forces = []

        data = {}
        energies = []
        frequencies = None
        normal_frequencies = None
        corrections = {}
        molecules = []
        structures = []
        species = []
        coords = []
        lattice = []
        errors = []
        basis_set = {}
        bset_header = []
        parse_geom = False
        parse_freq = False
        parse_bset = False
        parse_projected_freq = False
        job_type = ""
        parse_time = False
        time = 0
        for l in output.split("\n"):
            for e, v in error_defs.items():
                if l.find(e) != -1:
                    errors.append(v)
            if parse_time:
                m = time_patt.search(l)
                if m:
                    time = m.group(1)
                    parse_time = False
            if parse_geom:
                if l.strip() == "Atomic Mass":
                    if lattice:
                        structures.append(Structure(lattice, species, coords,
                                                    coords_are_cartesian=True))
                    else:
                        molecules.append(Molecule(species, coords))
                    species = []
                    coords = []
                    lattice = []
                    parse_geom = False
                else:
                    m = coord_patt.search(l)
                    if m:
                        species.append(m.group(1).capitalize())
                        coords.append([float(m.group(2)), float(m.group(3)),
                                       float(m.group(4))])
                    m = lat_vector_patt.search(l)
                    if m:
                        lattice.append([float(m.group(1)), float(m.group(2)),
                                        float(m.group(3))])

            if parse_force:
                m = force_patt.search(l)
                if m:
                    forces.extend(map(float, m.groups()[5:]))
                elif len(forces) > 0:
                    all_forces.append(forces)
                    forces = []
                    parse_force = False

            elif parse_freq:
                if len(l.strip()) == 0:
                    if len(normal_frequencies[-1][1]) == 0:
                        continue
                    else:
                        parse_freq = False
                else:
                    vibs = [float(vib) for vib in l.strip().split()[1:]]
                    num_vibs = len(vibs)
                    for mode, dis in zip(normal_frequencies[-num_vibs:], vibs):
                        mode[1].append(dis)

            elif parse_projected_freq:
                if len(l.strip()) == 0:
                    if len(frequencies[-1][1]) == 0:
                        continue
                    else:
                        parse_projected_freq = False
                else:
                    vibs = [float(vib) for vib in l.strip().split()[1:]]
                    num_vibs = len(vibs)
                    for mode, dis in zip(
                            frequencies[-num_vibs:], vibs):
                        mode[1].append(dis)

            elif parse_bset:
                if l.strip() == "":
                    parse_bset = False
                else:
                    toks = l.split()
                    if toks[0] != "Tag" and not re.match(r"-+", toks[0]):
                        basis_set[toks[0]] = dict(zip(bset_header[1:],
                                                      toks[1:]))
                    elif toks[0] == "Tag":
                        bset_header = toks
                        bset_header.pop(4)
                        bset_header = [h.lower() for h in bset_header]

            elif parse_hess:
                if l.strip() == "":
                    continue
                if len(hessian) > 0 and l.find("----------") != -1:
                    parse_hess = False
                    continue
                toks = l.strip().split()
                if len(toks) > 1:
                    try:
                        row = int(toks[0])
                    except Exception:
                        continue
                    if isfloatstring(toks[1]):
                        continue
                    vals = [float(fort2py(x)) for x in toks[1:]]
                    if len(hessian) < row:
                        hessian.append(vals)
                    else:
                        hessian[row - 1].extend(vals)

            elif parse_proj_hess:
                if l.strip() == "":
                    continue
                nat3 = len(hessian)
                toks = l.strip().split()
                if len(toks) > 1:
                    try:
                        row = int(toks[0])
                    except Exception:
                        continue
                    if isfloatstring(toks[1]):
                        continue
                    vals = [float(fort2py(x)) for x in toks[1:]]
                    if len(projected_hessian) < row:
                        projected_hessian.append(vals)
                    else:
                        projected_hessian[row - 1].extend(vals)
                    if len(projected_hessian[-1]) == nat3:
                        parse_proj_hess = False

            else:
                m = energy_patt.search(l)
                if m:
                    energies.append(Energy(m.group(1), "Ha").to("eV"))
                    parse_time = True
                    continue

                m = energy_gas_patt.search(l)
                if m:
                    cosmo_scf_energy = energies[-1]
                    energies[-1] = dict()
                    energies[-1].update({"cosmo scf": cosmo_scf_energy})
                    energies[-1].update({"gas phase":
                                         Energy(m.group(1), "Ha").to("eV")})

                m = energy_sol_patt.search(l)
                if m:
                    energies[-1].update(
                        {"sol phase": Energy(m.group(1), "Ha").to("eV")})

                m = preamble_patt.search(l)
                if m:
                    try:
                        val = int(m.group(2))
                    except ValueError:
                        val = m.group(2)
                    k = m.group(1).replace("No. of ", "n").replace(" ", "_")
                    data[k.lower()] = val
                elif l.find("Geometry \"geometry\"") != -1:
                    parse_geom = True
                elif l.find("Summary of \"ao basis\"") != -1:
                    parse_bset = True
                elif l.find("P.Frequency") != -1:
                    parse_projected_freq = True
                    if frequencies is None:
                        frequencies = []
                    toks = l.strip().split()[1:]
                    frequencies.extend([(float(freq), []) for freq in toks])

                elif l.find("Frequency") != -1:
                    toks = l.strip().split()
                    if len(toks) > 1 and toks[0] == "Frequency":
                        parse_freq = True
                        if normal_frequencies is None:
                            normal_frequencies = []
                        normal_frequencies.extend([(float(freq), []) for freq
                                                   in l.strip().split()[1:]])

                elif l.find("MASS-WEIGHTED NUCLEAR HESSIAN") != -1:
                    parse_hess = True
                    if not hessian:
                        hessian = []
                elif l.find("MASS-WEIGHTED PROJECTED HESSIAN") != -1:
                    parse_proj_hess = True
                    if not projected_hessian:
                        projected_hessian = []

                elif l.find("atom               coordinates                        gradient") != -1:
                    parse_force = True

                elif job_type == "" and l.strip().startswith("NWChem"):
                    job_type = l.strip()
                    if job_type == "NWChem DFT Module" and \
                            "COSMO solvation results" in output:
                        job_type += " COSMO"
                else:
                    m = corrections_patt.search(l)
                    if m:
                        corrections[m.group(1)] = FloatWithUnit(
                            m.group(2), "kJ mol^-1").to("eV atom^-1")

        if frequencies:
            for freq, mode in frequencies:
                mode[:] = zip(*[iter(mode)]*3)
        if normal_frequencies:
            for freq, mode in normal_frequencies:
                mode[:] = zip(*[iter(mode)]*3)
        if hessian:
            n = len(hessian)
            for i in range(n):
                for j in range(i + 1, n):
                    hessian[i].append(hessian[j][i])
        if projected_hessian:
            n = len(projected_hessian)
            for i in range(n):
                for j in range(i + 1, n):
                    projected_hessian[i].append(projected_hessian[j][i])

        data.update({"job_type": job_type, "energies": energies,
                     "corrections": corrections,
                     "molecules": molecules,
                     "structures": structures,
                     "basis_set": basis_set,
                     "errors": errors,
                     "has_error": len(errors) > 0,
                     "frequencies": frequencies,
                     "normal_frequencies": normal_frequencies,
                     "hessian": hessian,
                     "projected_hessian": projected_hessian,
                     "forces": all_forces,
                     "task_time": time})

        return data
