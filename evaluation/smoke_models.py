from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os, subprocess, sys
root=Path(r"J:\My Drive\valid models")
video=Path(r"J:\My Drive\video_datasets_polyp_for_gradio_app\videos with polyps\videos with polyps\1_35.avi")
models={"yolovit_vit":root/"yolovit"/"VIT.pt","sepnet":root/"Weight_of_SEPNet.pth","pvt_pranet":root/"models"/"pvt_pranet_v1"/"weights.pth","chakranet":root/"models"/"chakranet"/"weights.pth"}
def test(item):
    key,weight=item
    dest=Path(os.environ["TEMP"])/"chakra-four-model-smoke"/key
    dest.mkdir(exist_ok=True,parents=True)
    with (dest/"smoke.log").open("w") as log:
        rc=subprocess.call([sys.executable,"-c","import sys,json;from pathlib import Path;from worker import run;print(json.dumps(run(sys.argv[1],*map(Path,sys.argv[2:]),limit=2)))",key,str(weight),str(video),str(dest)],stdout=log,stderr=log)
    print(key,rc,(dest/"smoke.log").read_text(errors="replace")[-700:],flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(test,models.items()))
