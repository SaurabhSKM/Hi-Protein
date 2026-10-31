"""Download Meteo-France monthly climate files for the training departments."""
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ml"))
import sources  # noqa: E402

depts = (ROOT / "ml" / "train_depts.txt").read_text().split()
print(f"fetching {len(depts)} departments", flush=True)
ok, fail = [], []
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(sources.download_meteo, d): d for d in depts}
    for f in as_completed(futs):
        d = futs[f]
        try:
            p = f.result()
            ok.append(d)
            print(f"  ok {d} {p.stat().st_size//1024} KB", flush=True)
        except Exception as e:
            fail.append((d, str(e)[:90]))
            print(f"  FAIL {d}: {e}", flush=True)
print(f"done ok={len(ok)} fail={len(fail)}", flush=True)
if fail:
    print("failures:", fail, flush=True)
