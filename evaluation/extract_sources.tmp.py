import zipfile
from pathlib import Path
z=zipfile.ZipFile(r'J:\My Drive\chakra_final_backend_99models.zip')
for n in z.namelist():
    rel=n.partition('/')[2]
    if rel=='seg_infer.py' or (rel.startswith('binary_seg/') and rel.endswith('.py')):
        p=Path('vendor')/rel
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(n))
