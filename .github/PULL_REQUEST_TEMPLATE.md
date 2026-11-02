<!--
Keep this short. The useful part of a PR here is usually the second section.
-->

## What this changes

<!-- One or two sentences. -->

## Does it move a number?

<!--
Delete this section if the change is purely cosmetic or structural.

Otherwise: which reported figure changes, in which direction, and by how much?
Say so even when the change makes the project look worse — the most valuable
corrections this repo has taken did exactly that. If a headline figure moves,
`make audit` reports whether the shift flips a recommendation.
-->

- Figure affected:
- Before → after:
- Flips a recommendation: yes / no / not checked

## Checks

- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] New or changed behaviour has a test
- [ ] If a data source, parameter or modelling choice changed, the relevant doc in
      `docs/` was updated in the same commit — provenance drifting out of date is a
      correctness bug in this project, not a documentation chore
- [ ] If an API response shape changed, `backend/app/schemas.py` and
      `docs/API.md` agree, and `make smoke` passes against a running API
