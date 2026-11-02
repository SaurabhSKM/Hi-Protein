"""Guards on the built frontend bundle.

These exist because of two failures that produced no error anywhere - not in the
console, not in the build log, not in any test - and were only found by a human
looking at the screen:

1. Leaflet's default map marker rendered as nothing after its stylesheet moved from a
   CDN to the bundle. Leaflet guesses its icon URL from where the CSS was loaded, and
   that guess 404s once the CSS is one hashed file with no `images/` directory beside
   it. The pin on the farmer tab simply stopped appearing.

2. The stylesheet itself came from unpkg, which silently defeated offline mode - the
   whole point of which is that the demo runs on conference wifi.

Both are invisible to every other kind of test, so they are asserted against the build
artefact directly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _dist_file(pattern: str) -> Path:
    if not DIST.exists():
        pytest.skip("frontend/dist not built; run `make build`")
    matches = sorted(DIST.glob(pattern))
    if not matches:
        pytest.skip(f"no built asset matching {pattern}; run `make build`")
    return matches[-1]


def _dist_index() -> str:
    """The built index.html, or skip.

    Every test in this module asserts on a build artefact, so every one of them has to
    skip when there is no build rather than fail. CI's Python job deliberately has no
    frontend build - the assertions here run in the job that does one - and a test that
    forgot this guard failed there while its three siblings skipped.
    """
    if not (DIST / "index.html").exists():
        pytest.skip("frontend/dist not built; run `make build`")
    return (DIST / "index.html").read_text(encoding="utf-8")


def test_index_html_loads_nothing_from_the_network():
    """Offline mode is a hard requirement, so the page may not need a CDN to render."""
    html = _dist_index()
    external = re.findall(r'(?:href|src)="(https?://[^"]+)"', html)
    assert not external, f"index.html pulls from the network: {external}"


def test_leaflet_marker_icons_are_bundled_not_guessed():
    """The regression that made the farmer tab's map pin invisible.

    Three icon files (marker, retina marker, shadow) are all small enough that Vite
    inlines them as data URIs, so the assertion is on the data URIs rather than on
    emitted files. If they ever exceed the inline limit this test should be relaxed to
    accept emitted .png assets instead - but it must keep asserting that SOMETHING
    resolves them.
    """
    js = _dist_file("assets/index-*.js").read_text(encoding="utf-8", errors="ignore")

    inlined = re.findall(r"data:image/png;base64,[A-Za-z0-9+/=]{30}", js)
    assert len(set(inlined)) >= 3, (
        f"expected at least 3 distinct inlined PNGs (marker, retina, shadow), "
        f"found {len(set(inlined))}"
    )

    # And the icon URLs must actually be handed to Leaflet, not merely bundled.
    assert "mergeOptions" in js
    assert "Icon.Default" in js


def test_bundled_css_has_no_unresolved_relative_image_urls():
    """Leaflet's own CSS references images/layers.png and friends.

    If the bundler did not rewrite those, the layers control renders broken in exactly
    the same silent way the marker did.
    """
    css = _dist_file("assets/index-*.css").read_text(encoding="utf-8", errors="ignore")
    unresolved = re.findall(r"url\((?:'|\")?images/[^)]+\)", css)
    assert not unresolved, f"unrewritten relative image urls in bundled CSS: {unresolved}"


def test_viewport_and_mobile_meta_survive_the_build():
    """The app is expected to be usable on a phone; these are the minimum."""
    html = _dist_index()
    assert 'name="viewport"' in html
    assert "width=device-width" in html
    assert "theme-color" in html
