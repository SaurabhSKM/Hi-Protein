# Running it

The short version lives in the [README](../README.md#quickstart). This is the full
set of ways to run the app, and the proxy and offline problems each one solves.

---

## Quickstart

```bash
make install          # python venv + npm
make data             # downloads Agreste + Météo-France, builds the training panel
make train            # trains and conformalises the quantile yield models
make regions          # IGN communes, the 42-department table, breeders, baked profiles
make test             # 299 tests
make build            # builds the frontend bundle
make serve            # the whole app on http://localhost:5173
```

`make regions` downloads 18,157 commune geometries from IGN (about a minute), derives
the department area table and each department's own baseline rotation from Agreste, and
bakes the per-department Monte Carlo the regional view and the siting optimiser read.
**After any change to the margin engine, re-run `make profiles`** — otherwise the
regional view will quietly disagree with the farmer view, because they read the same
baked numbers precisely so that they cannot. `make rotations` re-derives the baseline
rotations alone; it changes which crop a pulse is compared against, so it needs a
`make profiles` after it.

That bake is what keeps the regional and food views interactive: it covers all five
climate horizons, so every number those tabs show is a dictionary lookup rather than a
simulation. It takes about six minutes; `make profiles-fast` does the observed horizon
only in about seventy seconds, which is enough to check a margin-engine change but
leaves the food view's projected horizons computing live. `GET /health` reports which
horizons the bake covers under `profile_bake`, and which responses were pre-warmed at
startup under `warmed` — check it first if either tab feels slow.

`make serve` runs the API and serves the built frontend from the same process, so
there is one port, one origin, no CORS and no dev-server host check. Override the
port with `make serve PORT=8080`.

**In the workshop container, use `make app` instead.** An nginx sits in front with
only two routes: `/` goes to the code editor on 8080, and `/app` goes to this app on
8081 with the prefix forwarded intact. Serving on any other port is unreachable from
outside, because `/ports/<n>/` style paths match nginx's `location /` and land on the
editor, which answers 400. `make app` mounts the application under `/app` so
Starlette strips the prefix and every route inside keeps working unchanged.

Then open `https://<your-host>/app/`. **The trailing slash matters**: the bundle
resolves its asset and API URLs relative to the directory it was loaded from, which
is why `vite.config.js` sets `base: './'`. Without the slash you get a 307 to the
correct URL, so it works either way in a browser.

For frontend work you want hot reload instead, which needs two processes:

```bash
make api              # terminal 1: API only, with reload
make web              # terminal 2: Vite dev server, proxies /api to it
```

`make data` pulls about 59 MB and takes a few minutes on a good connection. Both
downloads are cached, so re-runs are fast. Once the cache is warm:

```bash
make offline          # serves entirely from local cache, no network at all
```

Offline mode produces byte-identical simulation results. It exists because the demo
runs on conference wifi.

**Running in a cloud workspace?** Use `make serve`. It avoids the problem entirely.

If you do use `make web`, Vite refuses requests whose `Host` header it does not
recognise, which is a DNS-rebinding guard that fires whenever the dev server is
reached through a proxy rather than on localhost. The symptom is a bare
`Blocked request. This host ... is not allowed.` page. `vite.config.js` already
allows the common tunnel domains (CloudFront, Codespaces, Gitpod, ngrok, Cloudflare).
For anything else:

```bash
VITE_ALLOWED_HOSTS=my-host.example.com make web   # or a comma-separated list
VITE_ALLOWED_HOSTS=true make web                  # disable the check entirely
```

If hot reload sits reconnecting behind an HTTPS proxy, set `VITE_HMR_HOST` to the
public hostname as well. That only affects live reloading, not the app.
