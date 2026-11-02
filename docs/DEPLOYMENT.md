# Deployment, and moving off AWS

Today this runs on the workshop container with CloudFront in front of it, served under
`/app/`. When that access ends, nothing in this repository stops working: there is no
AWS SDK, no S3 call, no hardcoded ARN, no CloudFormation. The only two mentions of AWS
anywhere in the code are a docstring in `scripts/serve_under_app.py` and two entries in
the dev-server host allow-list in `frontend/vite.config.js`. Both are harmless.

What you actually lose is **a public URL and a machine to run the Python on**.

---

## The one thing to know before choosing

**The frontend belongs on Vercel. The backend does not fit there.**

The dependency stack this project needs — numpy, pandas, scipy, scikit-learn, xgboost —
does not fit in a Vercel Python function. Vercel caps a function's deployment bundle at
roughly 250 MB uncompressed (check their current limit, it moves); measured here, the
whole container image comes to **605 MB**, of which the Python packages are the bulk. It
is not a near miss, and trimming will not close it.

One trap worth knowing either way: `xgboost` declares `nvidia-nccl-cu12` as a hard
dependency — **471 MB of CUDA libraries** that this project never touches, since the
model is a CPU-trained quantile ensemble scored one request at a time. Swapping in
`xgboost-cpu` takes the image from 1.32 GB to 605 MB. The `Dockerfile` already does this,
and explains why it has to rewrite the requirements line rather than pre-install the
package.

Two further mismatches, in case the size limit is ever lifted:

- **Cold starts.** The yield model takes ~1.7 s to unpickle and the baked profiles are
  ~1 MB of JSON. The app warms both once during FastAPI's lifespan. A serverless
  function pays that on every cold invocation.
- **Statefulness that looks like caching.** `data/cache/` accumulates open-data API
  responses on disk and is what makes offline mode work. Serverless filesystems are
  ephemeral, so every cold start would re-fetch from IGN.

So the shape is: **static frontend on Vercel, containerised API somewhere that runs
containers.** Below are three options, cheapest-effort first.

---

## Option A — Vercel frontend + container API (recommended)

This is the straightforward port and keeps all five screens fully working.

### 1. Deploy the API as a container

A `Dockerfile` is in the repo root and builds the whole thing — frontend bundle, Python
runtime, trained model, baked profiles — into one image.

```bash
docker build -t hi-protein .           # ~2 min warm, 605 MB
docker run -p 8080:8080 hi-protein     # check it locally first
curl -s localhost:8080/health
.venv/bin/python scripts/smoke.py --port 8080
```

This was verified on 2026-11-02: the image builds, the model unpickles inside it, all
five profile horizons load, the bundle is served from `/`, and all 23 smoke checks pass
against the running container — including the live IGN parcel fetch.

Any container host will take it. Rough fit for this workload (one small always-on
process, ~1 GB RAM, no database):

| Host | Why it suits this | Notes |
|---|---|---|
| **Fly.io** | `fly launch` reads the Dockerfile; a persistent volume for `data/cache/` is one line | Scale-to-zero available; expect a slow first request if you use it |
| **Render** | Deploys straight from the GitHub repo, free tier exists | Free tier sleeps after inactivity — a cold start here is slow, see above |
| **Railway** | Easiest Dockerfile deploy of the three | Usage-billed |
| **Google Cloud Run** | Generous free tier, scales to zero | Set `--min-instances=1` or accept cold starts |
| **A small VPS** (Hetzner, Scaleway) | Full control, flat ~€4–5/month, no cold starts | You maintain the box |

For a demo that must be fast when a judge clicks it, pick something that does **not**
scale to zero, or keep one instance warm.

Set these on the API host:

```
HIPROTEIN_CORS=https://your-app.vercel.app
HIPROTEIN_OFFLINE=0          # 1 if you baked data/cache into the image
PORT=8080                    # most hosts inject this themselves
```

`HIPROTEIN_CORS` is the one people forget. Locally the API and the bundle share an
origin, so CORS never comes up. On Vercel they do not, and the default allows localhost
only — the symptom is every panel showing "Backend unreachable" with a CORS error in the
browser console.

### 2. Deploy the frontend to Vercel

Import the GitHub repo in Vercel, then:

- **Root Directory:** `frontend`
- **Framework preset:** Vite (auto-detected)
- Build command and output directory come from `frontend/vercel.json`; leave them alone.
- **Environment variable**, for all environments:

  ```
  VITE_API_BASE = https://your-api-host.example.com/api/v1
  ```

  Note the `/api/v1` suffix — `frontend/src/lib/api.js` appends paths directly to this
  value. This is read at **build time**, so changing it needs a redeploy, not a restart.

That is the whole frontend story. The app has no server-side rendering, no API routes,
no client-side router and no authentication, so it is a pure static deploy and will sit
inside Vercel's free tier.

### 3. Verify, in this order

```bash
curl -s https://your-api-host/health            # model_trained: true, 42 departments
curl -s https://your-api-host/api/v1/reference  # ~41 KB
make smoke PORT=…                               # or point scripts/smoke.py at the host
```

Then open the Vercel URL and check one panel on each tab. The failure you are looking
for is CORS, and it is unmistakable in the browser console.

---

## Option B — one container, no Vercel

Skip Vercel entirely. The image built by the `Dockerfile` already serves the bundle and
the API from one process on one port, which is how the app runs locally and in the
workshop container.

**This is simpler and has fewer failure modes than Option A**: one origin, so no CORS, no
`VITE_API_BASE`, no second deploy to keep in sync. The reason to prefer Option A anyway
is that Vercel gives you a free global CDN, preview deployments per pull request, and a
tidy `*.vercel.app` URL to put on a slide.

Put Cloudflare in front for TLS and caching if you want the CDN without the split.

---

## Option C — Vercel only, static demo

Worth knowing about, because of how much of this app is already precomputed.

Four of the five screens — Food, Region, Land, Method — read baked artifacts, not live
simulations. That is why they answer in ~2 ms. Only the Farmer view genuinely needs the
Python process, because it runs a Monte Carlo per request.

So you *could* export those four screens' responses to static JSON at build time and
deploy the whole thing to Vercel with no backend at all:

```bash
# sketch, not a provided script
for ep in regional-overview food-demand adoption/overview adoption/geometry \
          adoption/attribution adoption/rpg-change yield-trend model-report reference; do
  curl -s "localhost:5173/api/v1/$ep" > "frontend/public/api-snapshot/$ep.json"
done
```

...then point `lib/api.js` at the snapshot directory when a flag is set.

**The trade-off:** the Farmer view is the strongest screen in the product and it would
have to be dropped or reduced to a handful of pre-rendered examples. Take this option
only if you need a permanently free, zero-maintenance URL and can live without live
per-parcel simulation. If you do, write the snapshot date on the page — a static copy
with no visible vintage is exactly the stale-numbers failure mode the API's `no-store`
headers exist to prevent.

---

## Managing the data

Four tiers, and the honest answer is that **three of them need no management at all**.

| Tier | Where | Size | In git? | In the image? | What to do |
|---|---|---|---|---|---|
| Authored reference data | `backend/app/refdata/` | 1.5 MB | Yes | Yes | Nothing. Edit by hand, review in PRs. |
| Derived artifacts | `data/processed/`, `ml/artifacts/` | 10 MB | **Yes** | Yes | Nothing at runtime. Re-run the make target when inputs change. |
| Open-data response cache | `data/cache/` | 49 MB | No | Optional | One decision — see below. |
| Source downloads | `data/raw/` | 60 MB | No | No | Nothing. Only needed to rebuild. |

### Why the derived tier is committed

10 MB buys you a repository that runs on `git clone && make install && make serve`,
instead of one that first needs working access to four open-data APIs and about six
minutes of rebuilding. That property matters for CI, for container builds, for a judge
with a laptop, and most of all for deployment: **your deployed app needs no database and
no object storage, because its data is files that travel with the code.** That is the
reason this whole migration is as easy as it is.

Committing a 2.2 MB binary (`yield_model.joblib`) is a mild anti-pattern. At this size
it is the right trade. If it grows past ~50 MB, move it to Git LFS or to a GitHub
release asset downloaded at image build time — not to a runtime fetch, which would add a
network dependency to startup.

### The one decision: `data/cache/`

This holds IGN parcel geometry and ADEME Agribalyse responses. It is what makes
`HIPROTEIN_OFFLINE=1` work, and it is the only part of the app that writes to disk.

- **Bake it into the image** (un-ignore `data/cache` in `.dockerignore`, uncomment the
  `COPY` in the `Dockerfile`, set `HIPROTEIN_OFFLINE=1`). +49 MB to the image, and in
  exchange the container never calls an external API, cannot be slowed by one being
  down, and gives byte-identical results on every deploy. **Best for a demo you are
  being judged on.**
- **Mount a volume** at `/app/data/cache` and leave offline mode off. The cache warms
  itself as people click around and persists across restarts. Better for real use, where
  you want parcels nobody has looked at yet to resolve.
- **Neither.** It works — the cache rebuilds in the container's ephemeral filesystem —
  but every redeploy starts cold and a parcel click waits on IGN.

### `data/raw/` — the 60 MB you are not committing

Needed only by `make data`, which re-downloads it anyway. If you want a pinned copy so a
rebuild is reproducible even when a source URL changes, attach it to a GitHub release or
put it in cheap object storage (Cloudflare R2, Backblaze B2) — do not put it in git.
`docs/DATA_SOURCES.md` records the exact URL and parse recipe for every series, which is
the actual reproducibility guarantee.

### Refreshing the data later

Agreste publishes annually. When a new campaign lands:

```bash
make data && make train && make regions   # in that order
make test && make audit                   # then check nothing moved that shouldn't
```

Commit the regenerated `data/processed/` and `ml/artifacts/`, and redeploy. Note the
standing warning from `docs/ARCHITECTURE.md`: **conformal calibration must be re-fitted
every season**, because its coverage guarantee assumes exchangeability and a warming
climate breaks that.

---

## Checklist for going public

- [ ] `HIPROTEIN_CORS` set to the real frontend origin, not the default localhost list
- [ ] `VITE_API_BASE` set in Vercel, with the `/api/v1` suffix, and redeployed
- [ ] `/health` returns `model_trained: true` and 42 weather departments
- [ ] A rate limit in front of the POST endpoints — `/simulate-rotation` and
      `/optimise-sorters` both do real work. See [SECURITY.md](../SECURITY.md)
- [ ] The footer disclaimer intact: buyer prices are demo data, margins are operational
      gross margins and not farm profit
- [ ] Attribution for Agreste, Météo-France, IGN and ADEME visible — their open licences
      require it. See [NOTICE](../NOTICE)
