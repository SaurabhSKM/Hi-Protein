# Security

## What this application is

A read-only analytical service. No endpoint writes, deletes or mutates anything: the
API reads committed reference data, a trained model artifact and a disk cache, and
returns computed figures. There is no user account, no session, no database and no
upload path. Nothing a caller sends is persisted.

That shapes the realistic risk surface, which is:

- **Outbound fetches to open-data APIs** (IGN API Carto, ADEME Agribalyse). Responses
  are parsed into Pydantic models and cached on disk. Running with
  `HIPROTEIN_OFFLINE=1` removes this surface entirely.
- **Denial of service through cost.** `/simulate-rotation` runs a Monte Carlo and
  `/optimise-sorters` can be asked to verify its answer exactly with HiGHS. Request
  bounds are enforced in `backend/app/schemas.py` (`n_simulations` is capped at
  20,000, `k` at 26), but a public deployment should still sit behind a rate limit.
- **Response size.** `/adoption/geometry` is ~0.8 MB and the commune surface is
  larger. Serve it behind a CDN rather than straight off the origin.

## Reporting a vulnerability

Open a [private security advisory](../../security/advisories/new) rather than a public
issue. Please do not open a public issue for anything exploitable.

Expect an acknowledgement within a few days. This is a hackathon prototype maintained
by a small team, not a product with an on-call rotation — if you need a guaranteed
response time, say so in the advisory.

## Secrets

There are none in this repository, and none are needed: every data source it uses is
open and unauthenticated. `.env` is gitignored and `.env.example` documents the
variables — all of which are configuration, not credentials.

If you fork this and add a key, keep it in the environment. Do not put it in
`backend/app/refdata/`, which is committed.

## Before you deploy this publicly

- Set `HIPROTEIN_CORS` to your actual frontend origin. The default allows localhost
  only, which is correct for development and wrong for production.
- Put a rate limit in front of the POST endpoints, for the cost reason above.
- The figures are not advice. Keep the disclaimer in the application footer; it states
  that buyer prices are demo data and that margins are operational gross margins
  rather than farm profit.
