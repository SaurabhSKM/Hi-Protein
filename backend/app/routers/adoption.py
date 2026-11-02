"""Endpoints for the land-change view: how French land moved toward pulses.

Response models are deliberately absent here. Every payload is either a passthrough of
a baked artifact or a rollup of one, and both carry their own `_meta`/`provenance`
blocks that would have to be duplicated as pydantic models to no benefit - the schema
that matters is the artifact's, and it is versioned on disk by the script that writes
it. The endpoints that compute a decision, in main.py, do use strict models.

A missing artifact returns 503 with the command that bakes it, rather than a 500.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services import adoption

router = APIRouter(prefix="/adoption", tags=["land change"])


def _guard(fn, *args):
    try:
        return fn(*args)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/overview")
def overview() -> dict:
    """National area, share and yield per pulse per year, with the headline change.

    Reports peak year as well as first and last, because four of the five crops
    peaked before 2024: a first-to-last comparison on its own would describe a
    plateau-and-retreat as steady growth or as a simple decline, and neither is what
    the series shows.
    """
    out = dict(_guard(adoption.national))
    out["arrivals"] = _guard(adoption.arrivals_summary)
    return out


@router.get("/departments")
def departments(
    crop: str = Query(..., description="Internal crop key, e.g. green_lentil"),
) -> dict:
    """Per-department trajectory for one crop: area by year, change, arrival year."""
    return _guard(adoption.departments, crop)


@router.get("/geometry")
def geometry() -> dict:
    """Simplified IGN department polygons for the choropleth.

    Served separately from the data so the client fetches roughly 0.7 MB of boundaries
    once and then switches crop and year without refetching them. GZip middleware is
    already installed on the app.
    """
    return _guard(adoption.geometry)


@router.get("/attribution")
def attribution() -> dict:
    """What explains the change, and what this project cannot explain.

    Passthrough of ml/artifacts/adoption_report.json, including the negative
    cross-fitted weather increments and the list of unobserved drivers. The null
    result is the finding, so it is served rather than filtered.
    """
    return _guard(adoption.attribution)


@router.get("/rpg-change")
def rpg_change() -> dict:
    """Real RPG parcels in the Beauce across ten campaigns, 2015-2024."""
    return _guard(adoption.rpg_change)
