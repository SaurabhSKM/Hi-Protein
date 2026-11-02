import sys
from pathlib import Path

# `backend/`, not the repository root. Every test module imports `app.…`, which is how
# the application imports itself at runtime too, so the test and production module
# identities are the same object.
#
# Putting the repo root here as well would let `backend.app.config` and `app.config` both
# import successfully — as two distinct modules, with two copies of every @cache'd
# reference table and two loaded models. Don't.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _warm():
    from app.services import ml, weather
    ml.bundle()
    weather.panel()


@pytest.fixture
def base_request():
    from app.schemas import SimulateRotationRequest
    return SimulateRotationRequest(
        department_code="28", parcel_id="RPG-28-09412", area_ha=45.0,
        soil_type="deep_loam", has_livestock_ugb_5=False,
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        candidate_pulse_year2="field_pea", n_simulations=600, random_seed=7,
    )
