from pymatgen.analysis.defects.generators import ComplexMVGenerator
from pymatgen import MPRester

m = MPRester()
struct = m.get_structure_by_material_id("mp-984")
print(f"Fetching structure {struct.formula}...")
for mv_defect in ComplexMVGenerator(struct,"Au"):
    print(mv_defect.name)
    mv_defect_struct = mv_defect.generate_defect_structure((5,5,1))
    mv_defect_struct.to(filename=f"./{mv_defect.name}.cif")
