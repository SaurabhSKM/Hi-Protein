# Contributing

Thanks for looking. This project reports money figures to farmers and area figures to
policy readers, so the bar for a change is not "the tests pass" — it is "the number is
still defensible". Everything below follows from that.

## Setup

```bash
git clone <this repo> && cd Hi-Protein
make install        # python venv + npm
make serve          # app on http://127.0.0.1:5173
```

No `make data` needed to start. The derived artifacts — the trained yield model, the
weather and training panels, the baked department profiles — are committed, so a fresh
clone runs offline. You only need `make data` / `make train` / `make regions` if you are
changing how those are built. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```bash
make test           # 299 tests, ~50 s
make lint           # ruff
make smoke          # hit every endpoint against a running API
make audit          # perturb every numeric assumption, report which flip a decision
```

## The rules that actually matter here

**1. A number needs a provenance tag.** Every figure the API returns is tagged `[LIVE]`
(fetched from an open-data API this run), `[REPO]` (committed reference data) or
`[JUDG]` (an authored judgement). If you add a figure, tag it. A ministry reader will
check, and an untagged number is indistinguishable from an invented one.

**2. Demo data is labelled as demo data, everywhere.** Buyer contract terms and the
livestock holding directory are not real. They are labelled in the API response, in the
UI and in `NOTICE`. Do not quietly promote either to looking real.

**3. If you change a parameter, update the doc in the same commit.** `docs/DATA_SOURCES.md`
holds the URL and parse recipe for every fetched series. `docs/CHANGES_FROM_BLUEPRINT.md`
holds the reasoning for every departure from the Track 3 brief. Provenance that has
drifted out of date is a correctness bug, not a documentation chore.

**4. Report corrections that make the project look worse.** The most valuable changes
this repo has taken did exactly that — deriving each department's baseline rotation from
Agreste instead of hard-coding `soft_wheat / spring_barley / rapeseed` moved the
comparator to rapeseed and flipped two of eight test cases from positive to negative. The
old figures were flattering because the comparison was against a cheap cereal. Write that
up in the PR rather than around it.

**5. Validation is forward in time.** Train on 2010–2016, calibrate on 2017–2021, test on
2022–2024. Do not introduce a random K-fold: one growing season appears in both folds
across spatially correlated departments, so it leaks and the reported skill is fiction.

**6. No feature may use information from the season it predicts.** Weather features are
lagged to `t-1` throughout the adoption model for the same reason: a farmer sowing in
year `t` cannot know year `t`'s flowering rainfall.

**7. A null result is a result.** `ml/train_adoption.py` finds that weather explains none
of the year-on-year change in a department's pulse area, and the UI says so. Do not
"fix" it by dropping the cross-fitting that revealed it — the in-sample figure for the
same model is 69.6% and is meaningless.

## Code style

Python: ruff with the config in `pyproject.toml`, 100 columns, target 3.11. Comments in
this codebase explain *why*, usually by naming the failure that motivated the code —
match that register rather than narrating what the next line does.

Frontend: React 18 + Vite + Tailwind 4. Chart colours come from
`frontend/src/lib/landPalette.js`; do not hand-pick hex values per component.

## Tests

Add one for any new behaviour. The suite is organised by concern, not by file —
`test_finance.py` asserts invariants (a paired Monte Carlo under shared draws must
produce a difference distribution narrower than either leg), `test_rpg_codes.py` guards
the RPG vocabulary being year-dependent, `test_frontend_build.py` asserts things about
the built bundle that no runtime test can see. Put yours where its concern lives.

## Commits and PRs

Conventional-ish prefixes (`feat:`, `fix:`, `data:`, `docs:`, `refactor:`, `test:`) with
the subject under ~72 characters. Say in the body which figure moved and in which
direction. Fill in the PR template; its second section is the one that gets read.
