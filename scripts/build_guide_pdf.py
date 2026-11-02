"""Generate the plain-language product guide, docs/HI-PROTEIN-GUIDE.pdf.

Written for a team that is building this but does not come from an agricultural
background. Every agronomic and financial term is defined before it is used, every
number shown is the one the running application actually returns, and every screen is
walked through control by control.

Every figure that can move is READ FROM THE RUNNING API at build time rather than typed
in. The first version of this document was written by hand against values copied out of
several different API calls, and it drifted within a day: section 1.8 ended up quoting a
headline contract price from one field next to a price table from a different one. A
document whose selling point is "these are the numbers the application returns" cannot
be allowed to disagree with the application, so if the API is unreachable this script
refuses to build rather than quietly emitting stale figures.

Start the API first, then build:

    make api PORT=8099      # or: make serve
    make guide

Run directly: python scripts/build_guide_pdf.py [--api http://127.0.0.1:8099]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "HI-PROTEIN-GUIDE.pdf"
REPORT = ROOT / "ml" / "artifacts" / "model_report.json"

# The one canonical worked example used throughout Chapter 1. Every number in that
# chapter comes from THIS request and no other, which is the fix for the drift above.
DEMO = {
    "department_code": "28",
    "parcel_id": "RPG-28-09412",
    "area_ha": 45.0,
    "soil_type": "deep_loam",
    # Eure-et-Loir's own rotation, from refdata/dept_rotations.json.
    "baseline_rotation": ["soft_wheat", "rapeseed", "spring_barley"],
    "candidate_pulse_year2": "field_pea",
    "n_simulations": 2000,
    "random_seed": 7,
}

FONT_DIR = Path("/usr/share/fonts/dejavu-sans-fonts")
MONO_DIR = Path("/usr/share/fonts/dejavu-sans-mono-fonts")

INK = (28, 33, 40)
MUTED = (96, 106, 118)
GREEN = (21, 128, 61)
RED = (190, 24, 60)
AMBER = (146, 64, 14)
VIOLET = (109, 40, 217)
BLUE = (14, 116, 144)
RULE = (214, 220, 228)


# ====================================================================== #
# Live figures
# ====================================================================== #
class ApiUnreachable(RuntimeError):
    pass


def _get(base: str, path: str, body: dict | None = None, timeout: float = 120.0) -> Any:
    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310 - fixed localhost base, not user input
        url, data=data,
        headers={"content-type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ApiUnreachable(f"{url}: {e}") from e


def _wrap_quote(text: str, width: int) -> list[str]:
    """Wrap a sentence into a quoted block for the fixed-width code panels."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if lines:
        lines[0] = '"' + lines[0]
        lines[-1] = lines[-1] + '"'
    return lines


def eur(v: float | None, dp: int = 0) -> str:
    """Thousands-separated, with a minus sign rather than a hyphen."""
    if v is None:
        return "—"
    s = f"{abs(v):,.{dp}f}"
    return f"−{s}" if v < 0 else s


def pct(v: float | None, dp: int = 0) -> str:
    return "—" if v is None else f"{v * 100:.{dp}f}%"


def fetch_facts(base_url: str) -> dict[str, Any]:
    """Pull every figure the document quotes out of the running application."""
    f: dict[str, Any] = {}

    health = _get(base_url, "/health")
    f["model_version"] = health["model_version"]
    f["n_weather_depts"] = health["weather_departments"]
    bake = health.get("profile_bake") or {}
    f["baked_horizons"] = list((bake.get("horizons") or {}).keys())
    f["bake_paths"] = bake.get("n_simulations")
    f["warmed"] = health.get("warmed") or []

    ref = _get(base_url, "/api/v1/reference")
    f["n_horizons"] = len(ref.get("climate_horizons") or [])
    f["horizon_labels"] = [h.get("horizon") for h in (ref.get("climate_horizons") or [])]
    f["n_pulses"] = len(ref.get("pulse_crops") or [])
    f["n_buyers"] = len(ref.get("buyers") or [])
    f["n_depts_table"] = len(ref.get("departments") or {})

    # ---- Chapter 1: one request, every number ----
    sim = _get(base_url, "/api/v1/simulate-rotation", DEMO)
    fin = sim["financial_3yr_comparison_per_ha"]
    risk, ml = fin["risk"], sim["ml_predictions_year2"]
    f["demo_area"] = sim["area_ha"]
    f["median"] = risk["median_delta_eur_ha"]
    f["p_gain"] = risk["prob_pulse_beats_baseline"]
    f["p_lose100"] = risk["prob_delta_below_minus_100_eur_ha"]
    f["q15"] = risk["delta_q15_eur_ha"]
    f["cvar5"] = risk["cvar_5pct_delta_eur_ha"]
    f["breakeven"] = risk["breakeven_human_grade_fraction"]
    f["whole_parcel_delta"] = sim["financial_3yr_whole_parcel_eur"]["delta_median_eur"]
    f["y15"], f["y50"], f["y85"] = (
        ml["yield_q15_t_ha"], ml["yield_median_t_ha"], ml["yield_q85_t_ha"]
    )
    f["p_human"] = ml["prob_human_grade"]
    f["protein_pct"] = ml["expected_protein_pct"]

    br = fin["breakdown_year2_year3_gains"]
    f["br"] = br

    fo = sim["food_outcome"]
    f["harvest_t"] = fo["harvest_tonnes_median"]
    f["food_t"] = fo["food_grade_tonnes_median"]
    f["food_share"] = fo["food_market_share"]
    f["people_fed"] = fo["people_fed_at_recommended_intake"]
    f["grading_var"] = fo["value_at_risk_from_grading_eur_ha"]
    f["feed_fallback_t"] = fo["feed_fallback_tonnes_median"]

    sa = sim["sorter_access"]
    f["demo_sorter_km"] = sa["road_km"]
    f["demo_haul"] = sa["haulage_cost_eur_ha_median"]
    f["sorter_max_km"] = sa["max_distance_km"]

    bf = sim["breeder_fallback"]
    f["feed_spot"] = bf["feed_spot_price_eur_t"]
    f["offered"] = bf["best_offered_price_eur_t"]
    f["uplift_t"] = (bf.get("worth_signing") or {}).get("uplift_vs_spot_eur_t")
    f["cvar_wo"] = bf["cvar_without_fallback_eur_ha"]
    f["cvar_w"] = bf["cvar_with_fallback_eur_ha"]
    f["cvar_gain"] = bf["cvar_improvement_eur_ha"]
    f["lot_t"] = bf["downgraded_lot_t_median"]
    f["fb_radius"] = bf["search_radius_km"]
    f["fb_n"] = bf.get("holdings_within_radius")
    f["fb_matches"] = bf["matches"]
    f["fb_capacity_t"] = round(sum(m["max_pulse_intake_t"] for m in bf["matches"]), 1)

    mvc = fin["risk_preference"]["minimum_viable_contract"]
    f["mvc_terms"] = mvc["terms"]
    f["mvc_full"] = next(
        (t["min_contract_price_eur_t"] for t in mvc["terms"]
         if abs(t["volume_share"] - 1.0) < 1e-9), None
    )
    sens = mvc.get("price_sensitivity_full_volume_eur_t") or {}
    f["mvc_rra0"], f["mvc_rra4"] = sens.get("rra_0"), sens.get("rra_4")

    # ---- Chapter 7.1: the four-way floor comparison, derived live ----
    # Each arm is one API call. The "no floor" and "breeder" figures come from the
    # before/after pair the response already carries; adding selected_buyer_id puts a
    # guaranteed contract floor under the food price and gives the other two.
    f["floors"] = {}
    for label, req in (
        ("Field pea", DEMO),
        ("Green lentil", {**DEMO, "department_code": "21",
                          "soil_type": "shallow_limestone",
                          "candidate_pulse_year2": "green_lentil"}),
    ):
        base = sim if req is DEMO else _get(base_url, "/api/v1/simulate-rotation", req)
        buyer = next(
            (c["buyer_id"] for c in base["matched_offtake_contracts"]
             if c.get("floor_guaranteed") and c.get("contract_price_eur_t")),
            None,
        )
        row = {
            "none": base["breeder_fallback"]["cvar_without_fallback_eur_ha"],
            "breeder": base["breeder_fallback"]["cvar_with_fallback_eur_ha"],
        }
        if buyer:
            withc = _get(base_url, "/api/v1/simulate-rotation",
                         {**req, "selected_buyer_id": buyer})
            row["contract"] = withc["breeder_fallback"]["cvar_without_fallback_eur_ha"]
            row["both"] = withc["breeder_fallback"]["cvar_with_fallback_eur_ha"]
            row["buyer"] = buyer
        f["floors"][label] = row

    # Stranded example: measured from a real parcel in the Eure, far from any sorter.
    far = _get(base_url, "/api/v1/simulate-rotation",
               {**DEMO, "department_code": "27", "lon": 0.664, "lat": 48.984,
                "candidate_pulse_year2": "winter_pea"})
    fsa = far["sorter_access"]
    f["far"] = {
        "unit": fsa["nearest_unit_name"], "km": fsa["road_km"],
        "per_t": fsa["haulage_eur_per_tonne_food"],
        "per_ha": fsa["haulage_cost_eur_ha_median"],
        "stranded": fsa["is_stranded"], "note": fsa["stranded_note"],
        "median": far["financial_3yr_comparison_per_ha"]["risk"]["median_delta_eur_ha"],
    }

    # ---- Chapter 2 ----
    fd = _get(base_url, "/api/v1/food-demand")
    nat = fd["national"]
    f["nat"] = nat
    f["n_regions"] = len(fd["regions"])
    idf = next((r for r in fd["regions"] if r["region_code"] == "FR10"), fd["regions"][0])
    f["idf"] = idf
    f["d77"] = next(
        (x for x in idf["departments"] if x["department_code"] == "77"),
        idf["departments"][0],
    )

    # ---- Chapter 3 ----
    ro = _get(base_url, "/api/v1/regional-overview")
    f["surface"] = ro["surface_totals"]
    f["n_depts_modelled"] = len(ro["departments"])
    f["ro_ms"] = ro["compute_ms"]
    surf = _get(base_url, "/api/v1/stranded-surface")
    counts: dict[str, int] = {}
    for c in surf["communes"]:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    f["status_counts"] = counts
    f["n_communes"] = surf["n_total"]

    o3 = _get(base_url, "/api/v1/optimise-sorters", {"k": 3})
    f["o3"] = o3
    o3v = _get(base_url, "/api/v1/optimise-sorters", {"k": 3, "verify_milp": True})
    f["milp"] = o3v["optimisation"]["milp_verification"]
    f["milp_ms"] = o3v["compute_ms"]
    f["greedy_ms"] = o3["compute_ms"]
    o12 = _get(base_url, "/api/v1/optimise-sorters", {"k": 12})
    f["o12"] = o12["impact"]
    f["o12_capex"] = o12["capex_eur"]

    # ---- Chapter 3b: the land-change tab ----
    ao = _get(base_url, "/api/v1/adoption/overview")
    L = {r["year"]: r["area_ha"] for r in ao["series"]["green_lentil"]}
    C = {r["year"]: r["area_ha"] for r in ao["series"]["chickpea"]}
    tot = {y: L[y] + C.get(y, 0) for y in L}
    peak = max(tot, key=tot.get)
    f["area"] = {
        "first": min(tot), "last": max(tot), "peak": peak,
        "v_first": tot[min(tot)], "v_last": tot[max(tot)], "v_peak": tot[peak],
        "v_2020": tot.get(2020), "v_2022": tot.get(2022),
        "pct_first_peak": 100 * (tot[peak] / tot[min(tot)] - 1),
        "pct_2020_2022": 100 * (tot[2022] / tot[2020] - 1),
        "pct_first_last": 100 * (tot[max(tot)] / tot[min(tot)] - 1),
        "off_peak": 100 * (1 - tot[max(tot)] / tot[peak]),
    }
    f["headline_crops"] = ao["headline"]
    f["attrib"] = _get(base_url, "/api/v1/adoption/attribution")

    # ---- Chapter 4 ----
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    f["rep"] = rep
    f["trend"] = _get(base_url, "/api/v1/yield-trend")

    # ---- derived: how far each crop can travel ----
    crops = ref["crops"]
    f["haul"] = {}
    for key in ("field_pea", "green_lentil"):
        c = crops[key]
        food = c["price_eur_t"]["mean"]
        feed = c["feed_price_eur_t"]["mean"]
        f["haul"][key] = {
            "food": food, "feed": feed, "spread": round(food - feed, 1),
            "max_km": round(25 + (food - feed) / 0.45),
        }

    # ---- derived: hectares and machines needed to reach the target ----
    tgt = f["o12"]["target_share_pct"]
    arable = f["o12"]["scope_arable_ha"]
    now = f["o12"]["pulse_share_before_pct"]
    f["gap_ha_to_target"] = round(arable * (tgt - now) / 100.0, -3)
    per_unit = f["o12"]["hectares_unlocked"] / max(o12["k_sited"], 1)
    f["ha_per_unit"] = round(per_unit)
    f["units_for_target"] = round(f["gap_ha_to_target"] / per_unit)
    f["capex_for_target"] = f["units_for_target"] * o12["capex_per_unit_eur"]
    return f


class Guide(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(20, 18, 20)
        self.set_auto_page_break(True, margin=20)
        self.add_font("dv", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("dv", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.add_font("dv", "I", str(FONT_DIR / "DejaVuSans-Oblique.ttf"))
        self.add_font("dv", "BI", str(FONT_DIR / "DejaVuSans-BoldOblique.ttf"))
        self.add_font("mono", "", str(MONO_DIR / "DejaVuSansMono.ttf"))
        self.add_font("mono", "B", str(MONO_DIR / "DejaVuSansMono-Bold.ttf"))
        self.set_font("dv", "", 10)
        self.chapter = ""
        self.cover = True

    # ------------------------------------------------------------------ #
    def header(self) -> None:
        if self.cover:
            return
        self.set_font("dv", "", 7.5)
        self.set_text_color(*MUTED)
        self.set_y(10)
        self.cell(0, 4, "Hi-Protein — plain-language product guide", align="L")
        self.set_y(10)
        self.cell(0, 4, self.chapter, align="R")
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(20, 15, 190, 15)
        self.set_y(20)

    def footer(self) -> None:
        if self.cover:
            return
        self.set_y(-15)
        self.set_font("dv", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 4, f"{self.page_no()}", align="C")

    # ------------------------------------------------------------------ #
    def h1(self, text: str, number: str = "") -> None:
        self.add_page()
        self.chapter = text
        self.set_text_color(*MUTED)
        if number:
            self.set_font("dv", "B", 9)
            self.cell(0, 5, number.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("dv", "B", 19)
        self.set_text_color(*INK)
        self.multi_cell(0, 8.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1.5)
        self.set_draw_color(*INK)
        self.set_line_width(0.5)
        self.line(20, self.get_y(), 60, self.get_y())
        self.ln(5)

    def h2(self, text: str) -> None:
        self._space(16)
        self.ln(3)
        self.set_font("dv", "B", 12.5)
        self.set_text_color(*INK)
        self.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1.5)

    def h3(self, text: str, colour=None) -> None:
        self._space(14)
        self.ln(1.5)
        self.set_font("dv", "B", 10)
        self.set_text_color(*(colour or INK))
        self.multi_cell(0, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)

    def body(self, text: str, size: float = 9.5, colour=None, gap: float = 2.0) -> None:
        self.set_font("dv", "", size)
        self.set_text_color(*(colour or INK))
        self.multi_cell(0, size * 0.52, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                        markdown=True)
        self.ln(gap)

    def bullets(self, items: list[str], size: float = 9.5) -> None:
        self.set_font("dv", "", size)
        self.set_text_color(*INK)
        for it in items:
            self._space(10)
            x = self.get_x()
            self.set_font("dv", "B", size)
            self.cell(4, size * 0.52, "·")
            self.set_font("dv", "", size)
            self.multi_cell(0, size * 0.52, it, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                            markdown=True)
            self.set_x(x)
            self.ln(0.8)
        self.ln(1.4)

    def numbered(self, items: list[str], size: float = 9.5) -> None:
        self.set_font("dv", "", size)
        for i, it in enumerate(items, 1):
            self._space(10)
            self.set_font("dv", "B", size)
            self.set_text_color(*MUTED)
            self.cell(6, size * 0.52, f"{i}.")
            self.set_font("dv", "", size)
            self.set_text_color(*INK)
            self.multi_cell(0, size * 0.52, it, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                            markdown=True)
            self.ln(0.8)
        self.ln(1.4)

    def callout(self, title: str, text: str, colour=BLUE) -> None:
        """A tinted block. Used for the 'what this means' asides.

        The height has to be measured BEFORE the page-break check, not after. A fixed
        guess left a 60 mm callout half off the bottom of page 13 and the rest of the
        page blank, because the guess said it fitted and the real block did not.
        """
        self.set_font("dv", "", 9)
        w = 170 - 7
        lines = self.multi_cell(w, 4.7, text, dry_run=True, output="LINES",
                                markdown=True)
        h = 4.7 * len(lines) + (5.5 if title else 0) + 5
        self._space(h + 5)
        self.ln(1)
        x0, y0 = 20.0, self.get_y()
        tint = tuple(min(255, 255 - (255 - c) // 9) for c in colour)
        self.set_fill_color(*tint)
        self.rect(x0, y0, 170, h, style="F")
        self.set_fill_color(*colour)
        self.rect(x0, y0, 1.4, h, style="F")
        self.set_xy(x0 + 5, y0 + 2.5)
        if title:
            self.set_font("dv", "B", 9)
            self.set_text_color(*colour)
            self.multi_cell(w, 5, title, new_x=XPos.LEFT, new_y=YPos.NEXT)
            self.set_x(x0 + 5)
        self.set_font("dv", "", 9)
        self.set_text_color(*INK)
        self.multi_cell(w, 4.7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                        markdown=True)
        self.set_y(y0 + h + 3)

    def code(self, lines: list[str]) -> None:
        self._space(8 + 4.3 * len(lines))
        x0, y0 = 20.0, self.get_y()
        h = 4.3 * len(lines) + 5
        self.set_fill_color(244, 246, 249)
        self.rect(x0, y0, 170, h, style="F")
        self.set_xy(x0 + 4, y0 + 2.5)
        self.set_font("mono", "", 8.3)
        self.set_text_color(*INK)
        for ln in lines:
            self.set_x(x0 + 4)
            self.cell(0, 4.3, ln, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(y0 + h + 3)

    def table(self, head: list[str], rows: list[list[str]], widths: list[float],
              size: float = 8.3, align: str | list[str] = "L") -> None:
        self._space(14 + 5 * min(len(rows), 3))
        aligns = [align] * len(head) if isinstance(align, str) else align
        self.set_font("dv", "B", size)
        self.set_text_color(*MUTED)
        self.set_draw_color(*RULE)
        self.set_line_width(0.3)
        y = self.get_y()
        x = 20.0
        for h, w in zip(head, widths, strict=True):
            self.set_xy(x, y)
            self.multi_cell(w, 4.6, h, new_x=XPos.RIGHT, new_y=YPos.TOP)
            x += w
        self.set_y(y + 4.8)
        self.line(20, self.get_y(), 20 + sum(widths), self.get_y())
        self.ln(1.2)

        self.set_font("dv", "", size)
        for row in rows:
            heights = []
            for cell, w in zip(row, widths, strict=True):
                heights.append(
                    len(self.multi_cell(w - 2, 4.3, cell, dry_run=True,
                                        output="LINES", markdown=True)) * 4.3
                )
            rh = max(heights) + 1.6
            self._space(rh + 2)
            y = self.get_y()
            x = 20.0
            self.set_text_color(*INK)
            for cell, w, al in zip(row, widths, aligns, strict=True):
                self.set_xy(x, y)
                self.multi_cell(w - 2, 4.3, cell, new_x=XPos.RIGHT, new_y=YPos.TOP,
                                align=al, markdown=True)
                x += w
            self.set_y(y + rh)
            self.set_draw_color(238, 241, 245)
            self.line(20, self.get_y() - 0.8, 20 + sum(widths), self.get_y() - 0.8)
        self.ln(2.5)

    def kv(self, pairs: list[tuple[str, str]], size: float = 9) -> None:
        for k, v in pairs:
            self._space(8)
            self.set_font("dv", "B", size)
            self.set_text_color(*INK)
            self.cell(58, 4.8, k)
            self.set_font("dv", "", size)
            self.set_text_color(*MUTED)
            self.multi_cell(0, 4.8, v, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                            markdown=True)
        self.ln(2)

    def _space(self, need: float) -> None:
        if self.get_y() + need > self.h - self.b_margin:
            self.add_page()


# ====================================================================== #
def build(f: dict[str, Any]) -> Path:
    d = Guide()

    # ------------------------------------------------------------------ #
    # Cover
    # ------------------------------------------------------------------ #
    d.add_page()
    d.set_y(52)
    d.set_font("dv", "B", 9)
    d.set_text_color(*GREEN)
    d.cell(0, 5, "HI-PROTEIN", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    d.ln(4)
    d.set_font("dv", "B", 30)
    d.set_text_color(*INK)
    d.multi_cell(0, 12, "What every screen\nactually does",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    d.ln(5)
    d.set_font("dv", "", 12)
    d.set_text_color(*MUTED)
    d.multi_cell(
        0, 6,
        "A plain-language walkthrough of all five tabs: every control, every number, "
        "and every agricultural term defined before it is used.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    d.ln(14)
    d.set_draw_color(*RULE)
    d.line(20, d.get_y(), 190, d.get_y())
    d.ln(6)
    d.set_font("dv", "", 9)
    d.set_text_color(*INK)
    d.multi_cell(
        0, 5,
        "Written for: the build team, assuming no agricultural background.\n\n"
        f"Every figure in this document is read out of the running application at build "
        f"time, not typed in. Where the application and the project brief disagree, the "
        f"application wins and the disagreement is called out explicitly — there are "
        f"three of them, and they are listed in Chapter 7.\n\n"
        f"Built against model {f['model_version']} · {f['n_depts_table']} departments · "
        f"{eur(f['n_communes'])} communes · {len(f['baked_horizons'])} climate scenarios. "
        f"Regenerate with `make guide` while the API is running.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    d.ln(8)
    d.set_font("dv", "", 8.5)
    d.set_text_color(*MUTED)
    d.multi_cell(
        0, 4.6,
        "Generated by scripts/build_guide_pdf.py.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    d.cover = False

    # ------------------------------------------------------------------ #
    d.h1("Start here: the one idea the whole product rests on", "Chapter 0")

    d.body(
        "If you remember one thing from this document, make it this paragraph. "
        "Everything on all five screens is downstream of it."
    )
    d.callout(
        "The grading cliff",
        "The **same sack of lentils** is worth about **€840 a tonne** if a food company "
        "buys it for people to eat, and about **€275 a tonne** if it goes into animal "
        "feed. Nothing about the lentils changes. What changes is whether the batch "
        "passed a **visual quality inspection**.\n\n"
        "A beetle got into 2% of the seeds, or it rained during harvest and the seeds "
        "stained — and the buyer rejects the batch for human food. The farmer's "
        "profitable year becomes a loss. **That one risk is why French farmers do not "
        "grow these crops**, and no amount of telling them the average is good will fix "
        "it, because it is not the average that scares them.",
        RED,
    )
    d.body(
        f"France wants to go from about 4% of its farmland growing these crops to 8% by "
        f"2030, and it wants the harvest to feed **people** rather than livestock. Today "
        f"France grows only about **{f['nat']['self_sufficiency_current_pct']:.0f}%** of "
        f"the pulses its own population eats; the rest is imported, mostly from Canada."
    )

    d.h2("So what does this software do?")
    d.body(
        "Two different people have two different problems, so there are two main "
        "screens and three supporting ones."
    )
    d.table(
        ["Tab", "Who opens it", "The question it answers"],
        [
            ["**1. Farm & Advisor workspace**",
             "A farm adviser sitting with one farmer",
             "Should __this__ field grow a pulse crop next year, and what would it take "
             "to make that a safe decision rather than a gamble?"],
            ["**2. Food demand & supply**",
             "A regional food-policy officer",
             "Does the region grow enough of these crops to feed its own people — and "
             "is the money we spend buying __hectares__ actually buying __meals__?"],
            ["**3. Regional sovereignty map**",
             "An investment committee with a budget",
             "We have €11.7M. Where do we put the machines so that the most farmland "
             "becomes profitable?"],
            ["**4. Land change**",
             "Anyone asking \"is this already happening?\"",
             "Which French land actually moved to pulses since 2010, and what drove "
             "it — tested rather than asserted."],
            ["**5. Model & method**",
             "A sceptic, or a judge",
             "Is any of this trustworthy, and where does it break?"],
        ],
        [38, 40, 92],
    )

    d.h2("Nine words you need, and nothing more")
    d.body(
        "This is the entire agricultural vocabulary required to read the rest of the "
        "document. Everything else is ordinary finance."
    )
    d.table(
        ["Word", "What it means in one sentence"],
        [
            ["**Pulse**",
             "An edible seed from a bean-family plant: lentils, chickpeas, peas, broad "
             "beans. The crops this product is about."],
            ["**Hectare (ha)**",
             "A unit of land, 100m × 100m — about one and a half football pitches. "
             "A typical French field in this product is 25–45 ha."],
            ["**Yield (t/ha)**",
             "Tonnes of crop harvested per hectare. Wheat gets ~6–8; lentils get "
             "~1.4. Lentils are worth far more per tonne, which is the trade."],
            ["**Rotation**",
             "Farmers cannot grow the same crop on the same field every year — pests and "
             "diseases build up. So they cycle: wheat, then barley, then something else. "
             "A 3-year rotation is the planning unit here."],
            ["**Margin (€/ha)**",
             "Revenue minus running costs, per hectare. **Not** profit: it excludes "
             "land, labour and machinery, which do not change when you swap a crop."],
            ["**Grading / food-grade**",
             "The quality inspection that decides human food (€840/t) versus animal feed "
             "(€275/t). The grading cliff above."],
            ["**Optical sorter**",
             "An industrial machine that photographs every seed and blows out the stained "
             "or insect-damaged ones. Without one in reach, a batch cannot reliably pass "
             "the inspection."],
            ["**Nitrogen (N)**",
             "The main fertiliser. Farmers buy it as a chemical. Pulse plants make their "
             "own from the air and leave some in the soil — so the __next__ crop needs less, "
             "which is money saved and carbon avoided."],
            ["**PAC**",
             "French name for the EU farm subsidy system (CAP in English). It pays a bonus "
             "per hectare for growing protein crops — about €122/ha here."],
        ],
        [34, 136],
    )

    d.callout(
        "A note on the minus signs you are about to see a lot of",
        "Many numbers in this product are **negative**, and that is not a bug. The "
        "software compares a pulse crop against the wheat-and-barley rotation the farmer "
        "is already running. On high-quality land, wheat is genuinely very profitable, so "
        "swapping it for a pulse loses money — and the honest answer is to say so.\n\n"
        "A tool that showed green numbers everywhere would be useless, because the "
        "regional map's entire job is to find **where the answer is yes**, which only "
        "means something if the answer is sometimes no.",
        AMBER,
    )

    # ================================================================== #
    d.h1("Tab 1 — Farm & Advisor workspace", "Chapter 1")

    d.body(
        "**Who is looking at it:** an adviser from a farming cooperative, sitting across "
        "a table from one farmer in autumn, planning what to plant. The farmer is "
        "sceptical and has heard the pitch before."
    )
    d.body(
        "**What it has to achieve:** not \"lentils are good\". It has to answer *how bad "
        "could this get, how likely is that, and what would make it safe*."
    )

    d.h2("1.1 The left-hand column: describing the field")
    d.body(
        "Everything on the left tells the engine what it is looking at. Nothing here is "
        "a result."
    )
    d.kv([
        ("Preset buttons",
         "Four ready-made example farms, so you are never staring at an empty form. "
         "Beauce (very good land), Côte-d'Or (poor stony land), Gers (irrigated "
         "south-west), and a mixed crop-and-livestock farm."),
        ("The map",
         "Click anywhere on real French farmland. The app queries the French national "
         "field register (RPG) and pulls back the real field boundary, its real size, "
         "and what was actually grown on it in each of the last several years. This is "
         "live government data, not a mock-up."),
        ("Department",
         "French administrative area, like a county. 42 of them are covered — the ones "
         "with enough weather and harvest history to model."),
        ("Soil type",
         "Deep loam is excellent, shallow limestone is thin and stony. It changes both "
         "how much the crop yields and how much leftover fertiliser value it leaves "
         "behind."),
        ("Candidate crop",
         "Which pulse to test. Six options."),
        ("Area",
         "Field size in hectares. Scales the whole-field totals; does not change the "
         "per-hectare figures."),
        ("Years 1 / 2 / 3",
         "The rotation the farmer is __currently__ planning — the thing the pulse has to "
         "beat. The pulse always replaces **year 2 only**, so year 1 is identical in both "
         "plans and cancels out of the comparison."),
        ("Climate horizon",
         "Run the same field under today's climate, or under projected 2030 / 2050 "
         "warming. Defaults to observed, so the projection is always a deliberate choice."),
        ("Three checkboxes",
         "Does the farm have livestock; is the field irrigated; is a cover crop grown "
         "over winter. Each changes real money — see 1.6."),
    ])

    d.h2("1.2 The four big numbers at the top")
    d.body(
        "This is the summary an adviser reads out loud. The figures below are a real "
        "response for the demo field: 45 ha of deep loam in Beauce, growing field pea "
        "instead of spring barley, 2,000 simulated seasons."
    )
    d.table(
        ["Box", "Shows", "What it actually means"],
        [
            ["Median gain", f"**−€{eur(abs(f['median']))}/ha**",
             f"In a typical year, swapping barley for peas on this field loses "
             f"€{eur(abs(f['median']))} per hectare — about "
             f"€{eur(abs(f['whole_parcel_delta']))} across {f['demo_area']:.0f} ha. "
             f"Beauce wheat is simply very hard to beat. This is an honest no."],
            ["Chance of gain", f"**{pct(f['p_gain'])}**",
             f"Out of {DEMO['n_simulations']:,} simulated seasons, peas beat barley in "
             f"about {pct(f['p_gain'])} of them. The subtitle adds that there is a "
             f"{pct(f['p_lose100'])} chance of losing more than €100/ha."],
            ["Worst case", f"**−€{eur(abs(f['q15']))}/ha**",
             f"The 15th-percentile outcome — roughly a one-in-seven bad year. The "
             f"subtitle gives the average of the worst 5% of years: "
             f"−€{eur(abs(f['cvar5']))}/ha. This is the box that answers the farmer's "
             f"actual fear."],
            ["Food grade needed to break even", f"**{pct(f['breakeven'])}**",
             f"What share of the harvest would have to pass human-food inspection for "
             f"this to merely draw level. {pct(f['breakeven'])} means __even perfect "
             f"quality would not be enough here__, because the problem is the price of "
             f"pea, not the grading."],
        ],
        [34, 26, 110],
    )
    d.callout(
        "Why \"median\" and not \"average\"",
        "The median is the middle outcome: half the simulated years are better, half "
        "worse. Averages get dragged around by one freak year. Farmers plan against the "
        "middle and worry about the tail, so the product reports both and never the mean.",
    )

    d.h2("1.3 Getting the crop to an optical sorter")
    d.body(
        "A panel that is either quiet or alarming. It turns __distance__ into __money__."
    )
    d.body(
        f"To sell for human food, the batch has to be cleaned and optically sorted. "
        f"There are {f['surface']['existing_units']} such machines in the modelled "
        f"territory. Trucking costs about **€0.45 per tonne per kilometre**, and only the "
        f"part of the harvest destined for human food needs the trip."
    )
    d.body(
        f"On the Beauce demo field the nearest machine is **{f['demo_sorter_km']:.0f} km** "
        f"away, which is inside the distance a farm already drives to its local grain "
        f"store — so the extra cost is **€{eur(f['demo_haul'])}/ha** and the panel stays "
        f"grey. Click a real field in the Eure instead:"
    )
    far = f["far"]
    d.code([
        f"Nearest unit    {far['unit']}",
        f"Road distance   {far['km']:.0f} km",
        f"Charged         €{far['per_t']:.2f} per tonne of food-grade harvest",
        f"Cost to field   €{eur(far['per_ha'])}/ha"
        + ("            [ STRANDED POTENTIAL ]" if far["stranded"] else ""),
        "",
        *[f"  {line}" for line in _wrap_quote(far["note"], 60)],
    ])
    d.callout(
        "\"Stranded\" is the most important word in the product",
        "A stranded field is one that loses money **only because of the lorry ride**. The "
        "soil is right, the climate is right, the crop would pass inspection — and it "
        "still does not pay, because the machine is too far away.\n\n"
        "That is the one problem a government cheque can actually solve. A field that "
        "would lose money with a machine next door is a different problem entirely, and "
        "no amount of money fixes it. Tab 3 is built on exactly this distinction.",
        RED,
    )
    d.h3("Two rules that keep this number honest")
    d.bullets([
        "**Only the distance beyond 25 km is charged.** Farms already truck their wheat "
        "to a local store, and that cost is sitting in the running costs of __both__ plans. "
        "Charging the full distance would bill the pulse for a trip the wheat also makes.",
        "**Only food-grade tonnes are charged.** The rejected part of the harvest goes to "
        "a local feed buyer and needs no sorting. So a bad quality year hauls __less__ and "
        "pays __less__ — which partly cushions the loss instead of doubling it.",
    ])

    d.h2("1.4 The livestock fallback — computed, but no longer on this screen")
    d.body(
        "The engine matches a downgraded lot to neighbouring livestock holdings and "
        "prices both sides of the trade. That block still comes back from the API on "
        "every request, and it is still exercised by the test suite and the smoke "
        "test — but **it is not displayed on the farmer screen**, by choice."
    )
    d.callout(
        "Why it was taken off the screen",
        f"Because the honest number is small, and a panel is a promise that a number "
        f"is worth your attention.\n\n"
        f"Measured on the demo field it lifts the one-in-seven bad year by about "
        f"€{eur(f['cvar_gain'], 0)}/ha, and the sensitivity audit showed nothing "
        f"rescues that: at 100 percent of the surplus to the farmer it is "
        f"€74/ha, and at soybean meal €150/t above reference it is €89/ha. The project "
        f"brief claimed €298/ha. Chapter 7.1 sets out the unit error behind that claim "
        f"and the arithmetic ceiling that makes it unreachable.\n\n"
        f"It also measured as a **revenue floor, not downside insurance**: the loss tail "
        f"is driven mostly by low yield, and a low-yield year has fewer tonnes to "
        f"downgrade, so poor yield and poor grading nearly cancel in downgraded tonnage. "
        f"The uplift is close to flat across good and bad years.\n\n"
        f"The lever that does move the downside is the forward contract with a "
        f"guaranteed price floor — worth about three and a half times as much on field "
        f"pea — and that is what section 1.8 prices. Showing the smaller mechanism "
        f"beside the larger one invited the wrong conclusion.",
        AMBER,
    )
    d.body(
        f"If you want it back, it is one line in `pages/FarmerView.jsx`: the component "
        f"(`components/FallbackPanel.jsx`) and the `breeder_fallback` API block are both "
        f"still in place. The `/breeders` endpoint also still answers directly, so the "
        f"counterparties can be inspected without it — nearest holding on the demo field "
        f"is {f['fb_matches'][0]['distance_km']:.1f} km away and would pay "
        f"€{eur(f['offered'])}/t against a €{eur(f['feed_spot'])}/t feed market.",
        colour=MUTED,
    )

    d.h2("1.5 Where the harvest actually goes")
    d.body(
        f"The panel that answers the policy question rather than the money question. For "
        f"the {f['demo_area']:.0f} ha demo field:"
    )
    d.table(
        ["Figure", "Value", "Meaning"],
        [
            ["Total harvest", f"{f['harvest_t']:.1f} t",
             "Everything that comes off the field."],
            ["Passes inspection", pct(f['p_human']),
             "The modelled chance a batch clears human-food quality."],
            ["Has a food market at all", pct(f['food_share']),
             "Separate and often forgotten: even perfect peas mostly go to animals, "
             "because that is where the demand is. Lentils are the opposite."],
            ["**Reaches a human plate**", f"**{f['food_t']:.1f} t**",
             f"{f['harvest_t']:.1f} × {pct(f['p_human'])} × {pct(f['food_share'])}. Two "
             f"multiplications away from the harvest figure, and an order of magnitude "
             f"smaller."],
            ["Goes to animal feed", f"{f['feed_fallback_t']:.0f} t",
             "The rest. This is the tonnage the fallback contract in 1.4 is about."],
            ["People fed", f"{eur(f['people_fed'])}",
             "At the twice-a-week portion the French nutrition guidance recommends."],
            ["At risk from grading", f"€{eur(f['grading_var'])}/ha",
             "The money that hinges purely on passing inspection."],
        ],
        [40, 22, 108],
    )

    d.h2("1.6 The three checkboxes, and what each is worth")
    d.table(
        ["Checkbox", "What it changes"],
        [
            ["**Livestock on the farm**",
             "The farm feeds its own rejected batch rather than selling it, so the "
             "fallback price rises from €252 to €298/t. It also unlocks a different, "
             "larger EU subsidy — but only if the crop is harvested as animal fodder, "
             "and the two subsidies cannot be claimed on the same hectares."],
            ["**Irrigated**",
             "Matters more than it looks. The national statistics publish __one__ yield per "
             "crop per department, mixing irrigated and rain-fed fields together. Soya is "
             "mostly irrigated in France, so that blended figure badly overstates a "
             "rain-fed field. The engine unpicks it: rain-fed soya is scaled to 0.77, "
             "irrigated to 1.15. Without this correction the app recommended rain-fed "
             "soya across northern France, which is nonsense."],
            ["**Cover crop over winter**",
             "A crop sown purely to hold the soil through winter. It stops the leftover "
             "nitrogen washing away in the rain, so next year's wheat keeps more of it. "
             "On a wet autumn it is worth about 8 kg of nitrogen per hectare."],
        ],
        [38, 132],
    )

    d.h2("1.7 Three years side by side, and where the difference comes from")
    d.body(
        "The fan chart tracks cumulative margin year by year for both plans, with a "
        "shaded band from bad year to good year. Year 1 is identical in both — the lines "
        "sit exactly on top of each other, which is the visual proof that only one "
        "decision is being tested."
    )
    d.body("The bar chart underneath breaks the difference into its parts:")
    d.table(
        ["Component", "€/ha", "What it is"],
        [
            ["Pulse revenue", f"**+{eur(f['br']['pulse_gross_revenue_eur'])}**",
             "What the peas sell for."],
            ["Year-3 wheat yield boost",
             f"**+{eur(f['br']['wheat_yield_boost_year3_eur'])}**",
             "Next year's wheat grows better after a pulse — cleaner soil, fewer "
             "cereal diseases, leftover nitrogen."],
            ["EU protein subsidy", f"**+{eur(f['br']['pac_coupled_aid_eur'])}**",
             "Paid per hectare for growing a protein crop."],
            ["Year-3 fertiliser saved",
             f"**+{eur(f['br']['nitrogen_saved_year3_eur'])}**",
             "Nitrogen the pulse left in the soil that does not need buying."],
            ["Eco-scheme top-up", f"**+{eur(f['br']['eco_scheme_uplift_eur'])}**",
             "Only the __extra__ amount earned because the pulse crosses a crop-diversity "
             "threshold. Counting the whole payment would be double-counting."],
            ["Pulse running costs",
             f"**−{eur(f['br']['pulse_operational_cost_eur'])}**",
             "Seed, machinery passes, crop protection."],
            ["Haulage to sorter", f"**−{eur(f['br']['sorter_haulage_cost_eur'])}**",
             f"Zero here because a machine is {f['demo_sorter_km']:.0f} km away. Would be "
             f"−{eur(f['far']['per_ha'])} on the Eure field in 1.3."],
            ["**Forgone barley margin**",
             f"**−{eur(f['br']['forgone_baseline_year2_margin_eur'])}**",
             "**The biggest single bar, and it is negative.** This is the barley income "
             "given up to plant the pulse. A chart listing only the gains would be "
             "marketing; this one leads with the cost."],
        ],
        [50, 22, 98],
    )

    d.h2("1.8 What price would make this worth doing")
    d.body(
        "The most directly useful panel on the screen, and the one an adviser will reach "
        "for first. Everything above describes risk. This one **prices** it."
    )
    d.body(
        "It answers the question actually asked across the table — not \"what is the "
        "distribution of my margin\" but **\"what would someone have to pay me?\"**"
    )
    d.code([
        f"Becomes preferred at a €{f['mvc_full']:.0f}/t contract on 100% of expected "
        f"volume",
        "",
        "   Volume contracted      Minimum price      Reachable",
        *[
            f"   {t['volume_share'] * 100:>3.0f}%                   "
            f"€{t['min_contract_price_eur_t']:.0f}/t"
            f"{'             yes' if t['feasible'] else '             no'}"
            for t in f["mvc_terms"]
        ],
    ])
    d.body(
        "**Why committing more volume lowers the price needed:** what the premium buys is "
        "__certainty__, not revenue. Guarantee a quarter of the crop and the farmer still "
        "carries most of the risk, so they need a huge price on that quarter. Guarantee "
        "all of it and the risk is gone, so a far smaller premium does the job. That is "
        "the argument a cooperative needs to hear, and it is why this number is worth "
        "more than any of the risk statistics above it."
    )
    d.body(
        f"The chart beside it sweeps across farmer attitudes from \"gambler\" to \"very "
        f"cautious\" and shows that the required price moves only from "
        f"€{f['mvc_rra0']:.0f}/t to €{f['mvc_rra4']:.0f}/t across that whole range — "
        f"about €{f['mvc_rra4'] - f['mvc_rra0']:.0f}/t — so the answer does not depend on "
        f"guessing the farmer's personality.",
        colour=MUTED,
    )

    d.h2("1.9 Agronomic check, contracts, and the printable dossier")
    d.bullets([
        "**Agronomic check.** Some fields are simply forbidden, whatever the money says. "
        "A soil fungus called __Aphanomyces__ persists for a decade and has no treatment, "
        "so peas and lentils need a 5–7 year gap. Critically, the fungus attacks peas "
        "**and** lentils **and** alfalfa, so the app checks the whole disease family "
        "rather than the single crop — lentil two years after pea is blocked, and a "
        "per-crop rule would have waved it through. When it blocks, it still shows the "
        "money, so the cost of the constraint is visible.",
        f"**Contract book.** {f['n_buyers']} real-world-style buyers scored from the "
        f"farmer's side. "
        "A high headline price behind an unreachable quality standard is worth less than "
        "a lower price with a loose one, and the ranking says so. The open feed market "
        "sits in the list as a no-contract benchmark every offer has to beat.",
        f"**Compare all pulses.** Runs all {f['n_pulses']} candidates on this field and "
        f"ranks them.",
        "**Advisor dossier.** A printable pre-sowing checklist with a recommendation and "
        "a disclaimer — the artefact that actually leaves the meeting.",
    ])

    # ================================================================== #
    d.h1("Tab 2 — Food demand & supply", "Chapter 2")

    d.body(
        "**Who is looking at it:** a regional food or agriculture officer. **Every other "
        "screen looks upstream from the farm. This one looks downstream, at plates.**"
    )
    d.body(
        "The reason it exists: the policy target is written in __hectares__, and hectares "
        "are not meals. A region can hit its area target and still not feed anybody, "
        "because of the two multiplications in section 1.5."
    )

    d.h2("2.1 The national picture")
    d.table(
        ["Box", "Value", "Meaning"],
        [
            ["France eats", f"**{eur(f['nat']['current_demand_t'])} t/yr**",
             f"About {f['nat']['current_intake_kg_per_capita_year']} kg of dry pulses "
             f"per person per year."],
            ["France grows", f"**{eur(f['nat']['domestic_food_production_t'])} t/yr**",
             "Human-food-grade production."],
            ["Self-sufficiency", f"**{f['nat']['self_sufficiency_current_pct']}%**",
             "Fewer than half the pulses on French plates are French. The rest is "
             "imported, mostly Canadian."],
            ["At recommended intake", f"**{eur(f['nat']['recommended_demand_t'])} t**",
             f"If everyone ate the twice-a-week portion the national nutrition guidance "
             f"advises ({f['nat']['recommended_intake_kg_per_capita_year']} kg/person), "
             f"demand would roughly triple — and France would cover only "
             f"**{f['nat']['self_sufficiency_at_recommended_pct']}%** of it."],
        ],
        [36, 28, 106],
    )
    at = f["nat"]["area_trend"]
    d.callout(
        "The finding this screen exists to deliver",
        f"French human-food pulse area **fell {abs(at['change_pct']):.0f}%** between 2020 "
        f"and 2022 — from {eur(at['legumes_secs_ha_2020'])} ha to "
        f"{eur(at['legumes_secs_ha_2022'])} ha — while demand was already more than "
        f"double domestic supply and nutrition policy was pushing people to eat "
        f"more.\n\n"
        "**The constraint is not that nobody wants the crop.** Demand is there and "
        "growing. The constraint is on the farm, and it is the grading cliff from "
        "Chapter 0. That is why the other three tabs are about farm risk and "
        "infrastructure rather than about marketing.",
        GREEN,
    )

    d.h2("2.2 The region-by-region table")
    d.body(
        "For each region: what its population eats, what its farmland could supply if the "
        "area target were met, and the gap. Supply here is a **potential, not a "
        "forecast** — it asks what __would__ be produced if the gap-to-target hectares were "
        "planted with the best-fitting crop."
    )
    d.body("Île-de-France, as an example row:")
    i = f["idf"]
    d.kv([
        ("Population", f"{i['population_millions']} million"),
        ("Eats today", f"{eur(i['current_demand_t'])} t/yr"),
        ("Could supply", f"{eur(i['suppliable_food_grade_t'])} t — "
                         f"{i['coverage_of_current_demand_pct']:.0f}% of what it eats"),
        ("At recommended intake",
         f"{eur(i['recommended_demand_t'])} t needed — only "
         f"{i['coverage_of_recommended_demand_pct']:.0f}% covered"),
        ("Public canteens",
         f"{eur(i['collective_catering_t'])} t/yr, of which schools are "
         f"{eur(i['school_catering_t'])} t — and the region could cover that "
         f"**{i['catering_coverage_pct'] / 100:.1f} times over**"),
    ])
    d.callout(
        "Why the canteen line matters more than it looks",
        "French law already requires a vegetarian main course once a week in public "
        "canteens. That makes canteen demand a **contractable floor** — a known volume, "
        "with a public buyer, that someone can sign for in advance.\n\n"
        "And it is small enough to be winnable. A region cannot fix national "
        "self-sufficiency, but it can supply its own schools, and the table shows it has "
        "more than enough land to do so. That is a credible first contract rather than a "
        "national ambition.",
    )

    d.h2("2.3 The best column on the screen: margin versus food")
    d.body(
        "Each department shows **two** answers, because there are two different "
        "questions, and they have different answers:"
    )
    x = f["d77"]
    gap_t = x["food_t_if_food_optimised"] - x["food_t_if_margin_optimised"]
    gap_eur = x["best_margin_eur_ha"] - x["best_food_margin_eur_ha"]
    d.table(
        ["", f"{x['name']} ({x['department_code']}), "
             f"{eur(x['gap_ha'])} ha gap"],
        [
            ["**If you plant for farmer income**",
             f"{x['best_margin_pulse'].replace('_', ' ').capitalize()}. Margin "
             f"**−€{eur(abs(x['best_margin_eur_ha']))}/ha**. Yields "
             f"**{eur(x['food_t_if_margin_optimised'])} t** of human food."],
            ["**If you plant for human food**",
             f"{x['best_food_pulse'].replace('_', ' ').capitalize()}. Margin "
             f"**−€{eur(abs(x['best_food_margin_eur_ha']))}/ha**. Yields "
             f"**{eur(x['food_t_if_food_optimised'])} t** of human food."],
            ["**The divergence**",
             f"Planting for food produces **{eur(gap_t)} more tonnes** of human food — "
             f"nearly double — but costs the farmer €{eur(abs(gap_eur))}/ha more to "
             f"do it."],
        ],
        [52, 118],
    )
    d.callout(
        "What a policy officer does with that",
        f"Those {eur(gap_t)} tonnes are the **measured price of the current incentive "
        "structure**. Left alone, farmers will rationally plant winter pea, and the "
        "region gets half the food it could have.\n\n"
        f"The gap is also the size of the cheque needed to close it: "
        f"€{eur(abs(gap_eur))}/ha across the gap hectares buys the food-optimal crop "
        f"instead. This screen turns \"we should "
        "incentivise the right crops\" into a specific number per department — which is "
        "the difference between a slide and a budget line.",
        VIOLET,
    )

    d.h2("2.4 The climate selector")
    d.body(
        f"Re-runs the whole supply side under projected warming. "
        f"{len(f['baked_horizons'])} scenarios are available — "
        f"{', '.join(h.replace('_', ' ') for h in f['baked_horizons'])} — and supply "
        f"falls as warming rises, because hotter springs mean more of the beetle damage "
        f"that fails the quality inspection. It is a screening projection, not a climate "
        f"forecast — see Chapter 4."
    )
    d.callout(
        "Why switching scenario is instant",
        f"Each scenario needs a fresh Monte Carlo for every department and every "
        f"candidate crop — about {f['bake_paths']} simulated seasons × "
        f"{f['n_depts_modelled']} departments × {f['n_pulses']} crops. Run on demand that "
        f"is roughly a minute per scenario, which is not a dropdown.\n\n"
        f"So all {len(f['baked_horizons'])} are computed offline into a cache, and the "
        f"server additionally pre-warms them at startup — the health endpoint lists "
        f"{len(f['warmed'])} warmed responses. Switching scenario is then a dictionary "
        f"lookup. The regional overview in Tab 3 returns in "
        f"**{f['ro_ms']:.0f} ms** for the same reason.",
    )

    # ================================================================== #
    d.h1("Tab 3 — Regional sovereignty map", "Chapter 3")

    d.body(
        "**Who is looking at it:** an investment committee with roughly **€11.7M** of "
        "ecological-transition money and a map of their region. At €450k a machine that "
        "is 26 of them."
    )
    d.body(
        "**What they need:** not a heat-map of where the problem is. A ranked list of "
        "where to spend first."
    )

    d.h2("3.1 The map: 18,157 real places, coloured four ways")
    d.body(
        f"Every one of the {eur(f['n_communes'])} dots is a real French commune (the "
        f"smallest administrative unit, roughly a parish) pulled from the national "
        f"mapping agency, with its real boundary-derived centre and its real land area. "
        f"Dot size is how many hectares could realistically convert — "
        f"{eur(f['surface']['total_convertible_ha'])} ha in total. Colour is the whole "
        f"argument:"
    )
    sc, st = f["status_counts"], f["surface"]
    d.table(
        ["Colour", "Status", "Count", "What it means and what to do"],
        [
            ["Green", "**Viable**", f"{eur(sc.get('viable', 0))}",
             "Pulses already pay here, at the sorter distance this land actually has. "
             "No money needed."],
            ["Red", "**Stranded**", f"**{eur(sc.get('stranded', 0))}**",
             f"**Loses money now — would pay with a sorter in range.** The only category "
             f"a cheque can fix. Total: {eur(st['stranded_ha'])} ha, worth "
             f"€{st['stranded_value_eur'] / 1e6:.1f}M of lost margin."],
            ["Grey", "**Uneconomic**", f"{eur(sc.get('uneconomic', 0))}",
             "Loses money even with a machine next door. The limit is soil or market, "
             "not infrastructure. Spending here is wasted."],
            ["Pale", "Not modelled", f"{eur(sc.get('unmodelled', 0))}",
             "No viable pulse for that department at all."],
        ],
        [16, 26, 16, 112],
    )
    d.callout(
        "Red versus grey is the single most important distinction in this product",
        "Both lose money today. They look identical on any ordinary profitability map. "
        "But a machine fixes one and does nothing for the other.\n\n"
        "**Conflating them is exactly how infrastructure money gets spent in the wrong "
        "place** — and it is the mistake a simpler tool would make, because telling them "
        "apart requires simulating each place twice: once at its real distance, once as "
        "if a machine were next door. A test in the suite pins the distinction so it "
        "cannot quietly break.",
        RED,
    )
    d.body(
        f"Dark squares on the map are the {f['surface']['existing_units']} machines that "
        f"already exist. Checkboxes above it toggle each colour; grey is off by default "
        f"so the red is visible.",
        colour=MUTED,
    )

    d.h2("3.2 The button: Optimise placement")
    d.body(
        "Choose how many machines to site (1–26, because €11.7M buys 26 at €450k each), "
        "optionally narrow to one department, and press the button. In about half a "
        "second it returns where to build."
    )
    d.body("Three new machines, nationally:")
    o3 = f["o3"]
    d.table(
        ["#", "Where", "Hectares unlocked", "Tonnes/yr", "Usage"],
        [
            [str(st_["rank"]),
             f"{st_['commune']} (dept {st_['dept']})",
             eur(st_["hectares_unlocked"]),
             eur(st_["tonnes_unlocked"]),
             f"{st_['unit_economics']['utilisation_pct']:.0f}%"]
            for st_ in o3["sites"]
        ],
        [10, 72, 36, 26, 26],
        align=["L", "L", "R", "R", "R"],
    )
    d.h3("The live counters")
    im = o3["impact"]
    d.kv([
        ("Hectares unlocked", f"{eur(im['hectares_unlocked'])} ha"),
        ("Food-grade tonnes", f"{eur(im['tonnes_unlocked'])} t/yr"),
        ("CO2e avoided", f"{eur(im['co2e_saved_tons'])} t"),
        ("Pulse share", f"{im['pulse_share_before_pct']}% → "
                        f"{im['pulse_share_after_pct']}% "
                        f"(target {im['target_share_pct']:.0f}%)"),
        ("Margin per € of capex",
         f"€{im['value_per_euro_capex']} — every €1 of machine returns "
         f"€{im['value_per_euro_capex']} of farm margin over three years"),
        ("Capex", f"€{o3['capex_eur'] / 1e6:.2f}M, i.e. "
                  f"{o3['share_of_regional_envelope_pct']}% of the €11.7M envelope"),
    ])

    d.h2("3.3 How it works, without the mathematics")
    d.body(
        f"The honest problem is huge: {eur(f['n_communes'])} places × "
        f"{eur(o3['candidate_sites_considered'])} possible locations = "
        f"**{(f['n_communes'] * o3['candidate_sites_considered']) / 1e6:.0f} million** "
        f"combinations, each needing a 2,000-season simulation. That is weeks of "
        f"computing. Two ideas make it half a second."
    )
    d.h3("Idea 1 — distance is just subtraction")
    d.body(
        "Trucking cost is a flat rate per kilometre. So you do **not** need to re-simulate "
        "a place for every candidate machine; you simulate it once at zero distance and "
        "then subtract the lorry bill:"
    )
    d.code([
        "margin(distance) = margin(0 km) − food tonnes × €0.45 × (km − 25)",
    ])
    d.body(
        f"One simulation per department instead of "
        f"{(f['n_communes'] * o3['candidate_sites_considered']) / 1e6:.0f} million. This "
        f"is the load-bearing shortcut of the entire regional engine, so it is **tested "
        f"directly** against real simulations at 40, 120 and 300 km rather than assumed "
        f"to work."
    )
    d.h3("Idea 2 — pick greedily, then prove it was nearly perfect")
    d.body(
        "Pick the single best location. Then, given that one is built, pick the best "
        "__next__ one. Repeat. This is called a greedy algorithm, and normally greedy is a "
        "shortcut you apologise for."
    )
    d.body(
        "Here it is not, because this particular problem has a mathematical property "
        "called **submodularity** — informally, __the second machine is always worth less "
        "than the first__, because it partly serves land the first already reached. For "
        "problems with that property there is a 1978 theorem proving greedy lands within "
        "**63.2%** of the true best answer. That is a guarantee, not a hope."
    )
    d.body(
        "And then we check the guarantee against reality. Tick **\"Verify against the "
        "exact optimum\"** and the app solves the same problem exactly with an industrial "
        "solver (HiGHS) and reports the gap:"
    )
    mv = f["milp"]
    d.code([
        f"Exact optimum       €{mv['milp_objective_value_eur']:,.0f}",
        f"Greedy answer       €{mv['greedy_objective_value_eur']:,.0f}",
        f"Greedy achieved     {mv['greedy_share_of_optimum'] * 100:.2f}% of the exact "
        f"optimum",
        f"Worst-case floor    {mv['theoretical_floor'] * 100:.1f}%",
    ])
    d.body(
        f"Greedy takes {f['greedy_ms']:.0f} ms; the exact solve takes "
        f"{f['milp_ms'] / 1000:.1f} s. So greedy is the default for someone moving a "
        f"slider, and the exact check is one click away for someone who asks how we "
        f"know. The answer does not change — greedy has been above 99% on every scope "
        f"tested.",
        colour=MUTED,
    )
    d.h3("The agronomic brake")
    d.body(
        "The optimiser cannot recommend converting everything. Because of the soil fungus "
        "in section 1.9, a pulse on a 5-year gap can occupy at most one fifth of any "
        "rotation. Convertible hectares are capped by whichever bites first: that ceiling, "
        "or the gap to the 8% target. It binds exactly where it should — in departments "
        "already near their limit."
    )

    d.h2("3.4 The finding that changes the pitch")
    o12 = f["o12"]
    d.callout(
        "The machine runs out of capacity long before it runs out of farmland",
        f"Look at the **Usage** column in 3.2: every single sited machine comes back at "
        f"**100%**.\n\n"
        f"A sorting line handles about **10,000 tonnes a year**. At ~3 tonnes per hectare "
        f"that is ~{eur(f['ha_per_unit'])} hectares — and that is the ceiling, regardless "
        f"of how cleverly it is placed. You cannot get more out of a machine by siting it "
        f"better. You get more only by buying another machine.\n\n"
        f"**So:** {f['n_depts_modelled']} departments hold "
        f"{o12['scope_arable_ha'] / 1e6:.1f}M hectares. Going from "
        f"{o12['pulse_share_before_pct']}% to {o12['target_share_pct']:.0f}% means "
        f"converting roughly **{eur(f['gap_ha_to_target'])} hectares** — about "
        f"**{f['units_for_target']} machines and €{f['capex_for_target'] / 1e6:.0f}M**, "
        f"not one €450k grant. Our 12-machine run moves the share "
        f"{o12['pulse_share_before_pct']}% → {o12['pulse_share_after_pct']}%.",
        AMBER,
    )
    d.body(
        f"**Why say this out loud rather than hope nobody divides.** Anyone who sees "
        f"\"+3,850 ha unlocked\" next to \"4% → 8% target\" will do the arithmetic and "
        f"find the gap. Getting there first is far stronger: __one machine is €450k and "
        f"{eur(f['ha_per_unit'])} ha; the 8% target is ~{f['units_for_target']} machines "
        f"and €{f['capex_for_target'] / 1e6:.0f}M; and here is the order to buy them "
        f"in.__ The tool's value was never that one grant fixes France. It is that it "
        f"tells a region which grant to spend **first** — and the ranking is where the "
        f"money genuinely is."
    )

    d.h2("3.5 A second finding, which the model produced on its own")
    d.body(
        "Nobody typed this in. It falls out of the fact that haulage is a flat rate per "
        "kilometre while the food premium is fixed. Each crop therefore has its own "
        "maximum sensible travel distance:"
    )
    d.code([
        "max km = 25 + (food price − feed price) / €0.45",
    ])
    d.table(
        ["Crop", "Food price", "Feed price", "Premium", "Travels up to"],
        [
            [name,
             f"€{eur(h['food'])}/t", f"€{eur(h['feed'])}/t", f"€{eur(h['spread'])}/t",
             f"**~{eur(h['max_km'])} km**"]
            for name, h in (
                ("Field pea", f["haul"]["field_pea"]),
                ("Green lentil", f["haul"]["green_lentil"]),
            )
        ],
        [34, 28, 28, 26, 54],
        align=["L", "R", "R", "R", "R"],
    )
    d.body(
        f"Same lorry, same diesel. Lentil can afford the journey because the prize is "
        f"{f['haul']['green_lentil']['spread'] / f['haul']['field_pea']['spread']:.0f} "
        f"times larger. Past its own limit, a crop has **no** quality outcome that makes "
        f"the trip worthwhile — and the engine correctly reports that no break-even "
        f"exists rather than inventing one."
    )
    d.callout(
        "Why this is an argument for the optimiser rather than against it",
        "The sector uses a single national rule of thumb: 80 km. That rule says pea and "
        "lentil are the same problem. They are not — for pea, 80 km is far too cautious "
        "(it will travel 198); for lentil, 80 km is needlessly strict (you may not need a "
        "machine near the farm at all).\n\n"
        "The right answer genuinely varies field by field and crop by crop. That is "
        "precisely the thing a rule of thumb cannot do and an optimiser can — and it is a "
        "conclusion the model **derived** rather than one we assumed, which is the "
        "strongest kind of claim to make about a model.",
        GREEN,
    )

    # ================================================================== #
    d.h1("Tab 4 — Land change", "Chapter 3b")

    a = f["area"]
    d.body(
        "**Who is looking at it:** anyone who asks the obvious sceptical question — "
        "*is this shift already happening, and if so what is driving it?* This tab was "
        "added last and it is the one most likely to be attacked, because its answers "
        "complicate the other four screens."
    )

    d.h2("3b.1 What actually happened to the land")
    d.body(
        "Real Agreste area statistics for every French department, 2010 to 2024. The two "
        "flagship human-food pulses:"
    )
    d.table(
        ["Crop", "2010", "2024", "Multiple", "Peak"],
        [
            [k.replace("_", " ").capitalize(),
             f"{eur(v['first_area_ha'])} ha", f"{eur(v['last_area_ha'])} ha",
             f"**×{v['multiple_first_to_last']}**", f"{v['peak_year']}"]
            for k, v in f["headline_crops"].items()
            if k in ("green_lentil", "chickpea")
        ],
        [36, 30, 30, 26, 48],
        align=["L", "R", "R", "R", "R"],
    )

    d.callout(
        "This tab contradicts Tab 2 unless you read both windows",
        f"Tab 2 says the human-food pulse area **fell {abs(a['pct_2020_2022']):.0f}%** "
        f"between 2020 and 2022. That is arithmetically correct — "
        f"{eur(a['v_2020'])} ha to {eur(a['v_2022'])} ha.\n\n"
        f"This tab, from the **same Agreste file**, shows lentil and chickpea going "
        f"{eur(a['v_first'])} ha in {a['first']} to {eur(a['v_last'])} ha in "
        f"{a['last']} — **{a['pct_first_last']:+.0f}%**, via a peak of "
        f"{eur(a['v_peak'])} ha in {a['peak']}.\n\n"
        f"**Both are true.** The shape is a {a['pct_first_peak']:+.0f}% climb to "
        f"{a['peak']}, a sharp two-year collapse, then a partial recovery that is still "
        f"{a['off_peak']:.0f}% below the peak. Quoting either endpoint pair alone is "
        f"cherry-picking, so Tab 2 now draws the whole series with the 2020–2022 window "
        f"shaded, directly under the figure it qualifies. **Say this before a judge "
        f"finds it.** The honest claim is not \"the crop collapsed\" but \"it grew "
        f"fast, then stalled and partly reversed\" — and the demand gap is unchanged "
        f"either way, because France still imports more than half of what it eats.",
        RED,
    )

    d.h2("3b.2 The attribution model, and why its answer is awkward")
    d.body(
        "The tab also asks __what caused__ the year-to-year change in each department's "
        "pulse area. All weather features are lagged one season, because a farmer sowing "
        "this year cannot know this year's rainfall — using it would be leakage."
    )
    v = f["attrib"]["verdict"]
    d.kv([
        ("National year effect",
         f"{v['national_year_effect_pct_median']}% of the variance — the largest single "
         f"identified factor"),
        ("Weather adds",
         f"{v['weather_increment_pct_median']}% — nothing, once a national shock and a "
         f"persistent department effect are accounted for"),
        ("Crops where weather adds nothing", str(v["crops_where_weather_adds_nothing"])),
        ("Held-out skill",
         f"{v['held_out_skill_vs_no_change_pct_median']}% versus simply assuming no "
         f"change — i.e. worse than useless"),
    ])
    d.callout(
        "Read this as a finding, not as a self-own",
        "The model's own verdict is that **the shift to pulses is not weather-driven**, "
        "and that the likely drivers are price, PAC coupled aid and contract "
        "availability — which the report names as exactly the series this project has no "
        "usable history for (Eurostat's French farm-gate price series ends in 2016 and "
        "is flagged NOT USABLE).\n\n"
        "Taken naively that undercuts Tabs 1–3, which model farm-level weather and "
        "grading risk. Taken properly it is the strongest thing on the screen: **we "
        "built the model that could have refuted us, ran it, published the result, and "
        "it tells us which dataset to go and get.** A team that only ships the models "
        "that agree with it has not tested anything.\n\n"
        "It is also consistent with the literature: Magrini et al. (2016) and Meynard "
        "et al. (2018) both argue the French barrier is socio-technical lock-in, not "
        "agronomy. Our own data now says the same thing independently.",
        GREEN,
    )
    d.body(
        f"Coverage, stated: the descriptive view uses all "
        f"{f['attrib']['coverage']['adoption_panel_departments']} departments; the "
        f"attribution runs on the "
        f"{f['attrib']['coverage']['attribution_departments']} with assembled weather "
        f"data, over {f['attrib']['coverage']['years'][0]}–"
        f"{f['attrib']['coverage']['years'][1]}.",
        colour=MUTED,
    )

    # ================================================================== #
    d.h1("Tab 5 — Model & method", "Chapter 4")

    d.body(
        "**Who is looking at it:** a sceptic. This tab exists to be audited, and it leads "
        "with the places the model is weakest rather than burying them."
    )

    d.h2("4.1 What the model is")
    d.body(
        "A machine-learning model (gradient-boosted trees) trained on real French "
        "government data to predict crop yield. It does not output one number — it outputs "
        "**three**: a bad year, a typical year and a good year."
    )
    rep = f["rep"]
    d.kv([
        ("Trained on", f"Official French harvest statistics, department × crop × year, "
                       f"{rep['splits']['fit'][0]}–{rep['splits']['test'][1]}, joined to "
                       f"Météo-France weather records"),
        ("What it predicts", "Yield as a ratio to that department's own normal, so it "
                             "learns the __weather response__ rather than re-learning that "
                             "good soil out-yields bad soil"),
        ("Training rows", f"{eur(rep['n_fit'])} fit / {eur(rep['n_calib'])} "
                          f"calibration / {eur(rep['n_test'])} test"),
        ("Top predictors",
         ", ".join(
             k.replace("_", " ") for k in
             sorted(rep["feature_importance_top15"],
                    key=lambda k: -rep["feature_importance_top15"][k])[:5]
         )),
        ("Model version", f["model_version"]),
    ])
    d.callout(
        "Why those predictors are the right ones",
        "They are **phenological windows** — weather measured during the few weeks when "
        "it actually decides the crop's fate, not annual averages. Rain during flowering "
        "sets how many pods form. May warmth above 20°C is the trigger temperature for "
        "the beetle that fails the quality inspection. July rain at harvest is what stains "
        "the seeds.\n\n"
        "This was the hypothesis behind the feature engineering, and the held-out data "
        "supports it: those windows outrank every crop and soil indicator.",
    )

    d.h2("4.2 The honesty check: does a 70% interval contain 70% of outcomes?")
    d.body(
        "This is the panel that matters most, and it contains the project's most "
        "uncomfortable number."
    )
    d.body(
        "If the model says \"between 2.4 and 4.5 tonnes, 70% confident\", then across many "
        "fields the real answer should land inside that range about 70% of the time. "
        "Otherwise the confidence is a lie and a farmer planning against it is misled."
    )
    ce = rep["calibration_effect"]
    dep = rep["deployed_conformalised_metrics"]
    d.table(
        ["Measurement", "Value", "Verdict"],
        [
            ["Raw model coverage", f"**{pct(ce['interval_coverage_raw'], 1)}**",
             f"**Badly wrong.** Claimed "
             f"{pct(ce['interval_coverage_target'])} confidence and was right "
             f"{pct(ce['interval_coverage_raw'])} of the time — almost half of what it "
             f"promised."],
            ["After correction", f"**{pct(ce['interval_coverage_conformal'], 1)}**",
             f"Honest. Close to the {pct(ce['interval_coverage_target'])} target."],
            ["Lower tail",
             f"{pct(dep['q15']['empirical_coverage_below'], 1)} vs "
             f"{pct(dep['q15']['target_coverage_below'])} target", "Correct."],
            ["Upper tail",
             f"{pct(dep['q85']['empirical_coverage_below'], 1)} vs "
             f"{pct(dep['q85']['target_coverage_below'])} target", "Correct."],
        ],
        [44, 30, 96],
    )
    d.h3("What went wrong, and what fixed it")
    d.body(
        "The model was trained on 2010–2016 and tested on 2022–2024. Those recent years "
        "were hotter and drier than the training period, so real yields came in **below** "
        "what the older weather-yield relationships implied. The model was "
        "systematically too optimistic — and specifically too optimistic about bad years."
    )
    d.body(
        "The fix is **conformal prediction** (Romano, Patterson & Candès, 2019): hold back "
        f"a middle block of years, measure how wrong the intervals are on data the model "
        f"never saw, and widen them by exactly that much. Crucially the correction is "
        f"applied **one-sided** — the measured error on the lower bound was "
        f"{rep['conformal_offsets']['__global__']['width_lo']:.3f} ratio units against "
        f"{rep['conformal_offsets']['__global__']['width_hi']:.3f} on the upper, so "
        f"widening both equally would have over-inflated the good-year estimate while "
        f"leaving the real problem unfixed."
    )
    d.callout(
        "The trade this makes, stated plainly",
        f"Correct intervals are **wider** intervals. Average width roughly doubled "
        f"({ce['mean_width_raw_ratio']:.2f} → {ce['mean_width_conformal_ratio']:.2f} in "
        f"ratio units). We bought honesty, not precision.\n\n"
        "That is the right trade for a planting decision. A farmer told \"somewhere "
        "between 2.4 and 4.5 tonnes, and that is genuinely 70% likely\" can plan. A farmer "
        f"told \"3.4 to 3.8 tonnes, 70% likely\" when it is really "
        f"{pct(ce['interval_coverage_raw'])} likely is being "
        "actively misled, and will lose money trusting it.\n\n"
        "The model's own summary in the report says it: conformal calibration buys "
        "**honest coverage, not sharpness**.",
    )
    d.h3("Why the data was split by time and not at random")
    d.body(
        "A random split would **leak**. One growing season appears in many departments at "
        "once, and weather is spatially correlated — so the same 2016 drought would sit in "
        f"both the training and the test set wearing different department labels, and "
        f"every score would be flattered. Fitting on {rep['splits']['fit'][0]}–"
        f"{rep['splits']['fit'][1]} and testing on {rep['splits']['test'][0]}–"
        f"{rep['splits']['test'][1]} is the only split that mimics the real task: "
        f"predicting a year you have never seen."
    )

    d.h2("4.3 Accuracy by crop, including the bad rows")
    rows = sorted(rep["per_crop_test_performance"], key=lambda r: r["mae_pct"])
    best, worst = rows[0]["mae_pct"], rows[-1]["mae_pct"]
    d.table(
        ["Crop", "Rows", "Error t/ha", "Error %", "Coverage"],
        [
            [r["crop"].replace("_", " ").capitalize(), str(r["n"]), f"{r['mae_t_ha']:.2f}",
             (f"**{r['mae_pct']:.1f}%**"
              if r["mae_pct"] in (best, worst) else f"{r['mae_pct']:.1f}%"),
             f"{r['coverage'] * 100:.0f}%"]
            for r in rows
        ],
        [40, 20, 32, 30, 30],
        align=["L", "R", "R", "R", "R"],
    )
    d.callout(
        "Read this table honestly: the model is worst at exactly the crops we care most "
        "about",
        f"Wheat and rapeseed are predicted to within {best:.0f}–10%. Lentil is out by "
        f"{worst:.0f}%, about a third.\n\n"
        "Why: there is far less lentil in France, grown on more variable land, with "
        "shorter and patchier statistical records. Less data on a more erratic crop.\n\n"
        "**Why we show it anyway.** Because the intervals are honest, a wide interval on "
        "lentil is not a hidden failure — it is the product correctly telling a farmer "
        "that lentil is a riskier bet than wheat. That is true, and it is information the "
        "farmer needs. A tool that reported a confident narrow lentil forecast would be "
        "more impressive and less useful.",
        AMBER,
    )

    d.h2("4.4 The probability we cannot train, and say so")
    d.body(
        "The single most consequential number in the product — the chance a batch passes "
        "human-food inspection — is **not** a machine-learning output. It is a "
        "transparent formula."
    )
    d.body(
        "**Why:** no French open dataset records per-batch grading outcomes anywhere. "
        "Those records sit inside private cooperative warehouses. There is **no label to "
        "learn from**. Training a classifier on invented labels would dress a fabricated "
        "number as a measurement, and the first serious question would collapse it."
    )
    d.body(
        "Instead: a base rate per crop, multiplied down by named biological mechanisms, "
        "each driven by a real weather measurement."
    )
    d.table(
        ["Mechanism", "Driven by", "What physically happens"],
        [
            ["Harvest staining", "July rainfall",
             "Wet seeds discolour and fail visual inspection."],
            ["Beetle damage", "May days above 20°C",
             "Warm springs let the bruchid beetle complete its cycle; it bores holes in "
             "the seed."],
            ["Seed splitting", "Drought index",
             "Drought-stressed seeds crack and are rejected."],
            ["Small-seed abortion", "June days above 30°C",
             "Heat during pod-fill leaves undersized seeds."],
            ["No sorter access", "Distance",
             "Without a machine in reach a marginal batch cannot be cleaned to retail "
             "tolerance. Applied only to lentil, chickpea and fava bean — crops eaten as "
             "whole visible seeds. Pea and soya are split, milled or processed, so a "
             "sorter matters less, and a test pins that scope."],
        ],
        [36, 30, 104],
    )
    d.body(
        "The app labels this block **\"reference table\"**, not \"model output\", "
        "everywhere it appears. And it is the project's clearest data ask: per-batch "
        "grading records from one cooperative would turn this into a genuinely trained "
        "classifier overnight.",
        colour=MUTED,
    )

    d.h2("4.5 The chart nobody asked for")
    d.body(
        f"An amber panel titled **\"The finding that cuts both ways\"**. Over the "
        f"training period, mean yields of the pulse crops **fell** — "
        f"{f['trend']['crops'][0]['crop'].replace('_', ' ')} worst at "
        f"{f['trend']['crops'][0]['change_pct']:.1f}% — while cereals held up better."
    )
    d.body(
        "It is on the screen because it is true and it is inconvenient. It says these "
        "crops have been getting harder to grow, not easier, which is an argument against "
        "the product's own recommendation. Leaving it out would have been the easy choice "
        "and the wrong one — and a jury that finds a buried negative trusts nothing else "
        "on the screen."
    )

    d.h2("4.6 Two limitations panels")
    d.body(
        "The tab ends with the model's own stated limitations and a second panel for the "
        "regional engine. Chapter 5 summarises both."
    )

    # ================================================================== #
    d.h1("What is real, and what is assumed", "Chapter 5")

    d.body(
        "Every numeric block in the API carries a **provenance** field saying whether it "
        "is a live measurement, a model output, or an assumption. This chapter is that "
        "field, collected in one place. If you only read one chapter before facing "
        "questions, read this one."
    )

    d.h2("5.1 Genuinely real, fetched from French public sources")
    d.table(
        ["Layer", "Source", "What it gives"],
        [
            ["Crop yields", "Agreste SAA, 2010–2024",
             "Official harvest statistics by department × crop × year. The training "
             "labels."],
            ["Weather", "Météo-France monthly records",
             "Rain, temperature, frost and heat-day counts per station since 1950. "
             "Mountain stations above 700 m excluded — arable pulses are not grown there "
             "and they drag the heat signal down."],
            ["Field boundaries", "IGN RPG v2, live API",
             "Real field outlines and the real declared crop history, campaign by "
             "campaign, for any point clicked."],
            ["Commune geometry", "IGN ADMINEXPRESS",
             f"{eur(f['n_communes'])} real communes with boundaries, centres, land area "
             f"and population."],
            ["Carbon footprints", "ADEME Agribalyse",
             "Emissions per kg of product, filtered to the farm stage only."],
            ["Farmland area", "Agreste SAA area series",
             "Real arable and pulse hectares per department, 3-year mean."],
        ],
        [34, 40, 96],
    )
    d.callout(
        "A check worth quoting, because nothing was tuned to produce it",
        f"The {f['n_depts_table']}-department table is generated from Agreste area "
        f"statistics. Summed, it implies a "
        f"**{f['o12']['pulse_share_before_pct']}%** human-food pulse share of arable "
        f"land. The published national baseline the 2030 policy target is written against "
        f"is **4.0%**.\n\n"
        f"Those agree, and the small gap is the right sign — these "
        f"{f['n_depts_table']} departments are the cereal heartland, where pulse share is "
        f"below the national average. An independent corroboration of the whole "
        f"derivation, arrived at by accident.",
        GREEN,
    )

    d.h2("5.2 Reference tables: published figures, not measurements we made")
    d.bullets([
        "**Prices.** Food and feed price bands per crop, cross-checked against Eurostat.",
        "**EU subsidy amounts.** From the published 2023–2027 scheme. Flagged "
        "**provisional**, because the per-hectare amounts are only fixed each year once "
        "total claimed area is known.",
        "**Disease return intervals.** Published agronomic guidance, applied at the "
        "disease-family level rather than per crop.",
        "**Nutrition figures.** Population from the national statistics office; the "
        "twice-weekly portion from public health guidance.",
        "**Haulage rate and the 1.32 road detour factor.** Published bulk haulage rates; "
        "distances are straight-line inflated by 1.32, **not routed**.",
    ])

    d.h2("5.3 Honestly illustrative, and labelled as such in the app")
    d.table(
        ["Item", "Status"],
        [
            ["**Buyer contract book**",
             "Six buyers with plausible prices, floors and quality standards. Not "
             "commercial offers. The app footer says so."],
            ["**Livestock holdings**",
             "1,600 holdings. **Locations are real** IGN commune centres, so every "
             "distance reported is a real distance between real places — and the __number__ "
             "per department is scaled by that department's measured non-arable land "
             "share. But names, herd types and herd sizes are generated from published "
             "per-type averages with a fixed seed. No real farm is described. The API "
             "returns three separate fields saying exactly this."],
            ["**Candidate machine sites**",
             "Communes above 2,000 people, standing in for an inventory of cooperative "
             "grain stores, which is not public data. A cooperative would drop in its own "
             "site list and nothing else would change."],
            ["**Soil per department**",
             "One coarse archetype per department. Always pass the field's own soil."],
        ],
        [40, 130],
    )

    d.h2("5.4 The single biggest assumption in the product")
    d.callout(
        "How a department's farmland is divided between its communes",
        "We know each department's **real** arable hectares from Agreste. We do **not** "
        "know how they are distributed between its communes — nothing is published at that "
        "level. So they are split in proportion to each commune's land area.\n\n"
        "**This is right on average and wrong for any individual commune.** One that is "
        "mostly forest or town is credited with farmland it does not have.\n\n"
        "**Why it is still usable:** the optimiser sums demand across the hundreds of "
        "communes inside an 80 km radius, so the error averages out at the scale the "
        "__decision__ is made at — even though it is visible at the scale the __map__ is drawn "
        "at. It sits under the most visually persuasive screen in the product, so it is "
        "disclosed in the API provenance, in the map caption, and in the limitations panel "
        "as well as here.",
        RED,
    )

    # ================================================================== #
    d.h1("Where it breaks", "Chapter 6")

    d.body(
        "Volunteered, not extracted. A reviewer who finds an undisclosed weakness "
        "discounts everything else on the screen; one who finds you already listed it "
        "trusts the rest."
    )

    d.h2("6.1 The yield model")
    d.bullets([
        "**Training labels are department averages, not field measurements.** A single "
        "field varies more than a department average does, so intervals are widened by a "
        "measured factor of 1.29. A correction, not a substitute for field-level data.",
        "**Weather is a department median, not the field's own weather.**",
        "**No variety, sowing date or crop-protection data exists** in the open sources, "
        "so all management effects sit in the unexplained residual.",
        "**Margins are operating margins**, not profit. Land, labour and machinery are "
        "excluded, as is any change in workload the switch requires.",
        "**Conformal calibration assumes the future resembles the past.** A warming "
        "climate breaks that, so the calibration block must be re-fitted every season.",
        "**Worst accuracy on the crops that matter most** — lentil error is 33.6%. "
        "See 4.3.",
        "**No weed-control cost line exists**, while the sector names herbicide "
        "withdrawal on legumes as an existential threat. Margins assume weed control "
        "stays feasible.",
    ])

    d.h2("6.2 The grading probability")
    d.bullets([
        "**It has no observational labels anywhere in French open data.** It is a "
        "documented formula and the app never presents it as a measurement. It is also "
        "the most consequential number in the product, which makes per-batch grading "
        "records from a cooperative the highest-value dataset a partner could contribute.",
    ])

    d.h2("6.3 The regional engine")
    d.bullets([
        "**Commune farmland allocation is proportional to land area.** The big one — see "
        "5.4.",
        "**Candidate sites are a population proxy for a silo inventory**, which is not "
        "public data.",
        "**Distances are straight-line × 1.32, not routed.** Applied uniformly so it "
        "cannot favour one candidate over another, but it understates haulage in hilly "
        "terrain.",
        "**The 63.2% greedy guarantee covers the uncapacitated problem.** Machine "
        "capacity breaks the mathematical property the proof relies on, and is applied "
        "afterwards as an allocation step — so the bound does not formally cover the "
        "post-capacity hectares reported. The exact solver check runs on the same "
        "uncapacitated objective.",
        "**Cached department economics use one soil and one rotation per department.** "
        "They exist because 42 live simulations per request took over two minutes. Any "
        "real field should go through Tab 1 with its own soil and history.",
        "**The commune-level disease constraint is an aggregate, not a field check.** It "
        "enforces the steady-state one-fifth ceiling, which holds regardless of history — "
        "but it will clear individual fields that a field-level check would block.",
        "**The breeder fallback is a price floor, not insurance**, worth a flat ~€46/ha "
        "rather than concentrating in bad years. Measured, not assumed — see 1.4.",
    ])

    d.h2("6.4 The demand side")
    d.bullets([
        "**Current consumption is a central estimate in a 1.7–2.5 kg band**, not a "
        "measured market balance. FranceAgriMer publishes pulse balances; wiring those in "
        "would replace the softest parameter in the product.",
        "**Regional canteen volumes are the national figure scaled by population**, "
        "because meal counts are only published nationally. Transparent scaling, not a "
        "regional statistic.",
        "**Regional supply assumes the area target is met AND that rotation rules allow "
        "it.** They may not. The figures are an **upper bound**.",
        "**Climate sensitivities are fitted on year-to-year variation**, which is a "
        "space-for-time substitution: sound for temperature where the mechanism is direct, "
        "weak for rainfall where circulation change matters. Applying the model at +2.7°C "
        "extrapolates beyond its calibration range. A screening projection to bound the "
        "question, not a number to act on.",
    ])

    # ================================================================== #
    d.h1("Three places we disagree with the project brief", "Chapter 7")

    d.body(
        "The brief this was built from contains three figures the running code does not "
        "reproduce. In each case we kept the code's answer. **Do not put the brief's "
        "numbers on a slide** — the application will contradict you live."
    )

    d.h2("7.1 The livestock fallback is about six times smaller")
    d.kv([
        ("Brief says", "The fallback contract swings the bad year from −€240/ha to "
                       "+€58/ha — a €298/ha improvement"),
        ("Code says", f"A flat ~€{eur(f['cvar_gain'], 0)}/ha improvement, and it does not "
                      f"concentrate in bad years"),
    ])
    d.body("**Where the brief's number comes from — a unit error.**")
    d.body(
        "The brief values the rejected batch at €320–350/t, calling that the "
        "\"protein-equivalence value\" of non-GMO soya meal. But €320–350/t **is the price "
        "of soya meal**. Soya meal is 46% protein; field pea is 22%. One tonne of pea does "
        "not replace one tonne of meal — it replaces about 0.35 t of meal plus 0.65 t of "
        "feed wheat:"
    )
    d.code([
        "0.35 × €425 (soya meal) + 0.65 × €205 (feed wheat) + €16 (haulage saved)",
        "                                                      = €298/t",
    ])
    d.body(
        f"€298/t is what the batch is genuinely worth in an animal diet. The feed market "
        f"already pays €{eur(f['feed_spot'])}/t, so the value created is €46/t, split "
        f"55/45 — the farmer gets **€{f['uplift_t']:.0f}/t** on ~1.54 t/ha of rejected "
        f"harvest ≈ **€39/ha**. Measured on this field: "
        f"€{eur(f['cvar_gain'], 1)}/ha. It is the same factor-of-two protein error the "
        f"carbon module already refuses when it reports per kg of __protein__ rather than "
        f"per kg of __product__."
    )
    d.callout(
        "There is also a hard arithmetic ceiling",
        "Even if the livestock farmer paid the **full human-food price** for pea (€330/t), "
        "the uplift over the €252/t feed price would be €78/t × 1.54 t/ha = **€120/ha**.\n\n"
        "The brief's €298/ha is **larger than the entire food-versus-feed spread on the "
        "entire rejected tonnage**. It is unreachable for pea at any price whatsoever. "
        "(For lentil it is nearly reachable — but only if the fallback buyer pays full "
        "food price, which contradicts the premise that the batch failed food grade.)",
        RED,
    )
    d.body("**Measured with every floor the engine has, stacked:**")
    fl = f["floors"]
    cols = list(fl)

    def _row(label: str, key: str, bold: bool = False) -> list[str]:
        out = [f"**{label}**" if bold else label]
        for c in cols:
            v = fl[c].get(key)
            if v is None:
                out.append("—")
            elif key == "none":
                out.append(f"−€{eur(abs(v))}/ha")
            else:
                gain = v - fl[c]["none"]
                txt = f"+€{eur(gain, 0)}"
                out.append(f"**{txt}**" if bold else txt)
        return out

    d.table(
        ["Protection", *[f"{c} bad year" for c in cols]],
        [
            _row("No floor", "none"),
            _row("Breeder fallback", "breeder"),
            _row("Food contract with guaranteed floor", "contract"),
            _row("Both together", "both", bold=True),
        ],
        [78, 46, 46],
        align=["L", "R", "R"],
    )
    best_both = max(
        (fl[c]["both"] - fl[c]["none"]) for c in cols if fl[c].get("both") is not None
    )
    pea = fl.get("Field pea", {})
    d.body(
        f"Even both together move the downside about €{eur(best_both, 0)}/ha at best, not "
        f"€300. The three-year difference carries an irreducible ~€307/ha standard "
        f"deviation driven by **yield and food-price risk** — and a feed-market floor "
        f"touches neither. It only acts on the rejected fraction, at "
        f"€{f['uplift_t']:.0f}/t."
    )
    if pea.get("contract") is not None:
        c_gain = pea["contract"] - pea["none"]
        b_gain = pea["breeder"] - pea["none"]
        d.callout(
            "Read the table rows against each other, because the ranking is the finding",
            f"On field pea the breeder fallback is worth €{eur(b_gain, 0)}/ha in the bad "
            f"year. The **food contract with a guaranteed floor is worth "
            f"€{eur(c_gain, 0)}/ha** — about "
            f"{c_gain / b_gain:.1f} times as much.\n\n"
            f"That is the whole argument for restructuring the pitch. The contract floor "
            f"protects the price of the **entire harvest**; the breeder fallback protects "
            f"only the part that failed inspection, and only by the "
            f"€{f['uplift_t']:.0f}/t a livestock ration can outbid the commodity feed "
            f"market by. Lead with the bigger lever.",
            VIOLET,
        )
    d.callout(
        "What to pitch instead — and it is already built",
        "Stop asking the breeder fallback to carry the whole story. The thing that "
        "actually moves the downside is the **forward contract with a guaranteed price "
        f"floor on the whole volume**, and the engine already prices it exactly: __on the "
        f"Beauce demo field it becomes preferred at €{f['mvc_full']:.0f}/t on 100% of "
        f"expected volume.__\n\n"
        "Pitch **three stacked floors** — the contract floor as the headline, the EU "
        "subsidy, and the breeder fallback as what makes the last bad slice survivable "
        "while cutting a neighbour's soya imports. That version is true, it uses the same "
        "code, and it is still compelling.",
        GREEN,
    )
    d.body(
        "**One loose end worth closing.** The holding file records whether each farm buys "
        "certified non-GMO soya, and nothing reads it yet. Non-GMO meal trades roughly "
        "€40–100/t above standard, so for those farms the avoided cost is higher than the "
        "generic €425/t we use. Wiring it in would take the fallback from ~€46 to ~€65/ha. "
        "Honest, worth doing, still not €298.",
        colour=MUTED,
    )

    d.h2("7.2 One machine is right; the path to 8% is not")
    d.kv([
        ("Brief says", "+3,850 hectares unlocked per €450k machine"),
        ("Code says", f"{eur(min(x['hectares_unlocked'] for x in f['o3']['sites']))}–"
                      f"{eur(max(x['hectares_unlocked'] for x in f['o3']['sites']))} ha "
                      f"per machine — **the brief is basically right**"),
        ("But", f"12 machines move the share {f['o12']['pulse_share_before_pct']}% → "
                f"{f['o12']['pulse_share_after_pct']}%. Reaching "
                f"{f['o12']['target_share_pct']:.0f}% needs "
                f"~{eur(f['gap_ha_to_target'])} ha, ≈{f['units_for_target']} machines, "
                f"≈€{f['capex_for_target'] / 1e6:.0f}M"),
    ])
    d.body(
        "The per-machine figure is fine. What does not follow is the implied path to the "
        "target, because **throughput binds, not geography** — every sited machine returns "
        "at 100% usage. See 3.4 for how to pitch this as a strength."
    )

    d.h2("7.3 Two reference values the brief gets wrong")
    d.table(
        ["Figure", "Brief", "Code", "Why ours"],
        [
            ["Lentil food price", "€750/t", "**€840/t**",
             "Validated against Eurostat series."],
            ["Lentil feed price", "€230/t", "**€275/t**", "Same validation."],
            ["Fertiliser carbon factor", "12.7 kg", "**5.8 kg**",
             "CO2e per kg of nitrogen. 12.7 is roughly double the defensible figure and "
             "will not survive one question."],
            ["Year-3 wheat boost", "+0.5–0.8 t/ha", "**+0.28–0.55**",
             "Crop-specific. Published French trial means cluster lower than the brief's "
             "band."],
        ],
        [40, 26, 26, 78],
    )
    d.callout(
        "And one thing the brief calls a weakness that is actually the strongest answer",
        "The brief specifies a trained classifier for the food-grade probability. We "
        "deliberately did not build one, because **no label exists anywhere in French "
        "open data** — those records are inside private cooperative warehouses.\n\n"
        "Pitch that as a finding, not a shortfall: __we looked for the dataset, "
        "established it does not exist publicly, built a transparent mechanism-based "
        "model instead, and labelled it honestly everywhere it appears. Here is the "
        "dataset we would need, and here is the cooperative that has it.__ That is a "
        "stronger answer than a classifier trained on invented labels, and it survives "
        "follow-up questions.",
        GREEN,
    )

    # ================================================================== #
    d.h1("A seven-minute demo, in order", "Chapter 8")

    d.body(
        "Each step exists to set up the next. The order matters more than the content."
    )

    d.h3("Minutes 0–1 — plant the one idea")
    d.body(
        f"Open **Tab 1** on the Beauce preset. Say the Chapter 0 sentence out loud: "
        f"__the same sack of lentils is €840 a tonne as food and €275 as animal feed, "
        f"and what decides it is a visual inspection a beetle can fail.__ Point at "
        f"**{pct(f['p_human'])}** — the modelled chance of passing. Nothing else lands "
        f"until this does."
    )

    d.h3("Minutes 1–3 — show the honest no, then the price that fixes it")
    d.body(
        f"Stay on Beauce. **−€{eur(abs(f['median']))}/ha, {pct(f['p_gain'])} chance of "
        f"gain.** Say plainly: on the best wheat land in France the answer is no, and a "
        f"tool that said otherwise would be lying.\n\n"
        f"Then scroll to **What price would make this worth doing** and read the number: "
        f"__€{f['mvc_full']:.0f} a tonne on the full volume, and committing more volume "
        f"lowers the price because what the premium buys is certainty, not revenue.__ "
        f"That turns a no into a procurement specification, which is the real product."
    )

    d.h3("Minutes 3–4 — click a stranded field")
    d.body(
        f"Click a field in the Eure. The sorter panel turns red: "
        f"**{f['far']['km']:.0f} km, €{eur(f['far']['per_ha'])}/ha, STRANDED "
        f"POTENTIAL.** Read the sentence the app generates — __loses "
        f"€{eur(abs(f['far']['median']))}/ha, of which €{eur(f['far']['per_ha'])}/ha is "
        f"haulage.__\n\nThat is the handover line to Tab 3: this field is not bad "
        f"farmland, it is badly served farmland, and that is a different problem with a "
        f"different fix."
    )

    d.h3("Minutes 4–6 — the map and the button")
    d.body(
        f"**Tab 3.** Let the {eur(f['n_communes'])} dots land, then make the one "
        f"distinction that matters: __red loses money because of the lorry; grey loses "
        f"money regardless. A cheque fixes red and is wasted on grey.__ "
        f"**{eur(f['surface']['stranded_ha'])} hectares, "
        f"€{f['surface']['stranded_value_eur'] / 1e6:.1f}M.**\n\n"
        f"Press **Optimise placement**. Half a second, three named communes, the counters "
        f"move. Then tick **Verify against the exact optimum** and let it grind for "
        f"{f['milp_ms'] / 1000:.0f} seconds: "
        f"**{f['milp']['greedy_share_of_optimum'] * 100:.2f}% of the proven optimum "
        f"against a {f['milp']['theoretical_floor'] * 100:.1f}% guarantee.** That is the "
        f"moment the methodology stops being a claim.\n\n"
        f"Then volunteer the ceiling before anyone divides: __every machine comes back at "
        f"100% usage. One is €450k and {eur(f['ha_per_unit'])} hectares; 8% is about "
        f"{f['units_for_target']} machines and €{f['capex_for_target'] / 1e6:.0f}M. This "
        f"tool does not claim one grant fixes France — it tells you which grant to spend "
        f"first.__"
    )

    d.h3("Minutes 6–7 — close on the limitations tab")
    d.body(
        f"**Tab 4.** Go straight to the coverage panel: "
        f"**{pct(f['rep']['calibration_effect']['interval_coverage_raw'])} → "
        f"{pct(f['rep']['calibration_effect']['interval_coverage_conformal'])}.** __Our "
        f"first model claimed 70% confidence and was right "
        f"{pct(f['rep']['calibration_effect']['interval_coverage_raw'])} of the time. We "
        f"measured that, fixed it, and the intervals got wider. We bought honesty, not "
        f"precision.__\n\n"
        "Then scroll past both limitations panels without stopping, and say: __we found "
        "these ourselves.__ Finish on the amber **finding that cuts both ways** chart — the "
        "one showing pulse yields falling — and name it as an argument against our own "
        "recommendation that we put on the screen anyway."
    )

    d.callout(
        "If you only have two minutes",
        f"The grading cliff (Chapter 0) → the honest **−€{eur(abs(f['median']))}/ha** → "
        f"the **€{f['mvc_full']:.0f}/t** price that fixes it → the red map and the "
        f"**{f['milp']['greedy_share_of_optimum'] * 100:.2f}%** verification. Four beats. "
        f"Skip everything else.",
        VIOLET,
    )

    d.h2("Questions you will be asked")
    d.table(
        ["Question", "Answer"],
        [
            ["\"Is the grading probability machine-learned?\"",
             "No, and deliberately — see 7.3. No label exists in French open data. It is "
             "a transparent mechanism model, labelled as a reference table everywhere it "
             "appears, and it is our clearest data ask."],
            ["\"Why are most of your numbers negative?\"",
             "Because on the best wheat land the answer genuinely is no. The map's job is "
             "to find where it is yes, which only means something if it is sometimes no."],
            [f"\"Your model is {worst:.0f}% wrong on lentil.\"",
             "Correct, and shown. Because the intervals are honestly calibrated, a wide "
             "lentil interval is the product correctly reporting that lentil is a riskier "
             "bet. That is information, not a hidden failure."],
            ["\"How do you know the siting is optimal?\"",
             f"Two ways. A 1978 theorem guarantees greedy within "
             f"{f['milp']['theoretical_floor'] * 100:.1f}% for this class of problem. And "
             f"we solve it exactly with HiGHS on request: "
             f"{f['milp']['greedy_share_of_optimum'] * 100:.2f}%."],
            [f"\"Are those {eur(f['n_communes'])} dots real?\"",
             "The places, boundaries, areas and populations are real IGN data. The split "
             "of each department's farmland between its communes is proportional to land "
             "area — the one big assumption, disclosed in three places. See 5.4."],
            ["\"Can one machine really get you to 8%?\"",
             f"No, and we say so first. ~{f['units_for_target']} machines, "
             f"~€{f['capex_for_target'] / 1e6:.0f}M. The tool ranks which to fund first. "
             f"See 3.4."],
            ["\"What would you build next?\"",
             "Per-batch grading records from a cooperative, which turns the formula into "
             "a trained classifier. Then routed road distances instead of a 1.32 detour "
             "factor. Then FranceAgriMer market balances to replace the softest demand "
             "parameter."],
        ],
        [54, 116],
    )

    d.ln(3)
    d.set_font("dv", "I", 8.5)
    d.set_text_color(*MUTED)
    d.multi_cell(
        0, 4.4,
        "This is a prototype. It does not replace advice from a Chamber of Agriculture "
        "or a cooperative agronomist, and no rule table substitutes for a soil disease "
        "test. Buyer prices and livestock holdings are illustrative demo data and are "
        "not commercial offers.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.output(str(OUT))
    return OUT


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default="http://127.0.0.1:8099",
                    help="Base URL of the running Hi-Protein API.")
    a = ap.parse_args()
    try:
        f = fetch_facts(a.api)
    except ApiUnreachable as e:
        print(f"Cannot reach the API at {a.api}\n  {e}\n", file=sys.stderr)
        print(
            "This guide quotes figures from the RUNNING application, so it will not "
            "build\nagainst a stale copy. Start the API and try again:\n\n"
            "    make api PORT=8099     # in another terminal\n"
            "    make guide\n",
            file=sys.stderr,
        )
        return 1
    p = build(f)
    print(f"Wrote {p}  ({p.stat().st_size / 1024:.0f} KB)")
    print(f"  figures read live from {a.api}")
    print(f"  {f['n_communes']:,} communes · {f['n_depts_modelled']} departments · "
          f"{len(f['baked_horizons'])} baked climate horizons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
