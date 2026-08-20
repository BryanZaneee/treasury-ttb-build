"""Generate api/fixtures/expectations.json and api/fixtures/applications.csv
from design_handoff_label_verification/fixtures-manifest.csv.

Ground truth per row is hand-derived by applying PRD §3.2's match/review/fail
rules to the manifest's `intended_defect` column.

Row 6 (vinos-del-sol-abv.jpg) deliberately contradicts its sources. The manifest
and the PRD §13 appendix both call it "none - clean reference", but the filename
encodes an "abv" defect (every other clean fixture is suffixed "-pass"), PRD
acceptance test 6 says verbatim "12.5% on label vs 13.5% filed -> fail", and the
image prints 12.5% Alc./Vol. cleanly with nothing else wrong. So it is an
application-vs-label content mismatch, not a manifest typo, and is treated here
as the ABV-mismatch fixture.

Run by hand when fixtures change: `uv run python scripts/build_fixtures.py`.
Output is committed; the running app never invokes this.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

WARNING_VERBATIM = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)
WARNING_REWORDED = (
    "GOVERNMENT WARNING: Drinking alcohol may be harmful to your health. "
    "Please enjoy responsibly and never drink and drive."
)

# `illegible` and `degraded` are the two per-field capture signals the reader
# reports. Illegible means the extractor could not read the field at all -> fail
# (PRD §3.2). Degraded means it read the field, but from a capture bad enough
# that the reading is not trustworthy on its own: an otherwise-matching field
# downgrades to review rather than match (PRD §3.2, "an otherwise-matching field
# ... read from a degraded capture"). Quality alone cannot carry this - two of
# the blurry fixtures and one angled one are expected to reach match - so the
# signal has to be per field, not per capture.

# field_key values follow PRD §3.1's table verbatim (brand, classType, abv,
# net, producer, origin, warning) - a different vocabulary than models.py's
# Python-conventional Application attribute names (brand, class_type, ...).

# Each row: filename -> (
#   applicant, beverage class,
#   app values (as filed), label values (as printed),
#   quality, illegible field keys, degraded field keys, expected per-field verdicts,
#   expected record verdict
# )
ROWS: list[dict[str, Any]] = [
    {
        "filename": "old-tom-pass.jpg", "applicant": "Old Tom Distillery LLC", "beverage": "Distilled Spirits",
        "app": {"brand": "Old Tom Distillery", "classType": "Kentucky Straight Bourbon Whiskey",
                  "abv": "45%", "net": "750 mL", "producer": "Old Tom Distillery, Bardstown, KY", "origin": None, "warning": True},
        "label": {"brand": "Old Tom Distillery", "classType": "Kentucky Straight Bourbon Whiskey",
                   "abv": "45% Alc./Vol. (90 Proof)", "net": "750 mL",
                   "producer": "Old Tom Distillery, Bardstown, KY", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "match",
    },
    {
        "filename": "stones-throw-caps.jpg", "applicant": "Stone's Throw Spirits Co.", "beverage": "Distilled Spirits",
        "app": {"brand": "Stone's Throw", "classType": "Kentucky Straight Bourbon Whiskey",
                  "abv": "45%", "net": "750 mL", "producer": "Stone's Throw Spirits, Loretto, KY", "origin": None, "warning": True},
        "label": {"brand": "STONE'S THROW", "classType": "Kentucky Straight Bourbon Whiskey",
                   "abv": "45% Alc./Vol. (90 Proof)", "net": "750 mL",
                   "producer": "Stone's Throw Spirits, Loretto, KY", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "review", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "review",
    },
    {
        "filename": "harbor-mist-nowarning.jpg", "applicant": "Harbor Mist Brewing", "beverage": "Malt Beverage",
        "app": {"brand": "Harbor Mist", "classType": "India Pale Ale",
                  "abv": "6.8%", "net": "12 FL OZ", "producer": "Harbor Mist Brewing, Astoria, OR", "origin": None, "warning": True},
        "label": {"brand": "Harbor Mist", "classType": "India Pale Ale",
                   "abv": "6.8% Alc./Vol.", "net": "12 FL OZ",
                   "producer": "Harbor Mist Brewing, Astoria, OR", "origin": None,
                   "warningPresent": False, "warningBody": None, "warningHeaderCase": None, "warningHeaderBold": None},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "fail"},
        "verdict": "fail",
    },
    {
        "filename": "cedar-ridge-titlecase.jpg", "applicant": "Cedar Ridge Vineyards", "beverage": "Wine",
        "app": {"brand": "Cedar Ridge", "classType": "Napa Valley Cabernet Sauvignon",
                  "abv": "14.2%", "net": "750 mL", "producer": "Cedar Ridge Vineyards, Rutherford, CA", "origin": None, "warning": True},
        "label": {"brand": "Cedar Ridge", "classType": "Napa Valley Cabernet Sauvignon",
                   "abv": "14.2% Alc./Vol.", "net": "750 mL",
                   "producer": "Cedar Ridge Vineyards, Rutherford, CA", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "title", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "review"},
        "verdict": "review",
    },
    {
        "filename": "lark-hollow-reworded.jpg", "applicant": "Lark Hollow Craft Spirits", "beverage": "Distilled Spirits",
        "app": {"brand": "Lark Hollow", "classType": "Small Batch Gin",
                  "abv": "44%", "net": "750 mL", "producer": "Lark Hollow Craft Spirits, Asheville, NC", "origin": None, "warning": True},
        "label": {"brand": "Lark Hollow", "classType": "Small Batch Gin",
                   "abv": "44% Alc./Vol. (88 Proof)", "net": "750 mL",
                   "producer": "Lark Hollow Craft Spirits, Asheville, NC", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_REWORDED, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "fail"},
        "verdict": "fail",
    },
    {
        "filename": "vinos-del-sol-abv.jpg", "applicant": "Sol Selections", "beverage": "Wine",
        "app": {"brand": "Viños del Sol", "classType": "Rioja Tempranillo",
                  "abv": "13.5%", "net": "750 mL", "producer": "Sol Selections, Miami, FL", "origin": "Product of Spain", "warning": True},
        "label": {"brand": "Viños del Sol", "classType": "Rioja Tempranillo",
                   "abv": "12.5% Alc./Vol.", "net": "750 mL",
                   "producer": "Sol Selections, Miami, FL", "origin": "Product of Spain",
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "fail", "net": "match",
                         "producer": "match", "origin": "match", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "iron-gate-blur.jpg", "applicant": "Iron Gate Rye Works", "beverage": "Distilled Spirits",
        "app": {"brand": "Iron Gate", "classType": "Straight Rye Whiskey",
                  "abv": "50%", "net": "750 mL", "producer": "Iron Gate Rye Works, Frederick, MD", "origin": None, "warning": True},
        "label": {"brand": "Iron Gate", "classType": "Straight Rye Whiskey",
                   "abv": "50% Alc./Vol. (100 Proof)", "net": "750 mL",
                   "producer": "Iron Gate Rye Works, Frederick, MD", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "blurry", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "match",
    },
    {
        "filename": "saltmarsh-glare.jpg", "applicant": "Saltmarsh Brewing Union", "beverage": "Malt Beverage",
        "app": {"brand": "Saltmarsh", "classType": "Gose Style Ale",
                  "abv": "4.5%", "net": "16 FL OZ", "producer": "Saltmarsh Brewing Union, Portland, ME", "origin": None, "warning": True},
        "label": {"brand": "Saltmarsh", "classType": "Gose Style Ale",
                   "abv": "4.5% Alc./Vol.", "net": "ILLEGIBLE",
                   "producer": "Saltmarsh Brewing Union, Portland, ME", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "glare", "illegible": ["net"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "fail",
                         "producer": "match", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "north-fen-pixel.jpg", "applicant": "North Fen Vodka Company", "beverage": "Distilled Spirits",
        "app": {"brand": "North Fen", "classType": "Vodka",
                  "abv": "40%", "net": "1 L", "producer": "North Fen Vodka Co., Duluth, MN", "origin": None, "warning": True},
        "label": {"brand": "ILLEGIBLE", "classType": "Vodka",
                   "abv": "40% Alc./Vol. (80 Proof)", "net": "1 L",
                   "producer": "North Fen Vodka Co., Duluth, MN", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "pixelated", "illegible": ["brand"], "degraded": [],
        "field_verdicts": {"brand": "fail", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "brasserie-verte-origin.jpg", "applicant": "Continental Beverage Imports", "beverage": "Malt Beverage",
        "app": {"brand": "Brasserie Verte", "classType": "Belgian Style Tripel",
                  "abv": "9.2%", "net": "330 mL", "producer": "Continental Beverage Imports, Newark, NJ",
                  "origin": "Product of Belgium", "warning": True},
        "label": {"brand": "Brasserie Verte", "classType": "Belgian Style Tripel",
                   "abv": "9.2% Alc./Vol.", "net": "330 mL",
                   "producer": "Continental Beverage Imports, Newark, NJ", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "angled", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "origin": "fail", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "quarry-house-units.jpg", "applicant": "Quarry House Cellars", "beverage": "Wine",
        "app": {"brand": "Quarry House", "classType": "Willamette Valley Pinot Noir",
                  "abv": "13.1%", "net": "750 mL", "producer": "Quarry House Cellars, Dundee, OR", "origin": None, "warning": True},
        "label": {"brand": "Quarry House", "classType": "Willamette Valley Pinot Noir",
                   "abv": "13.1% Alc./Vol.", "net": "75 cl",
                   "producer": "Quarry House Cellars, Dundee, OR", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "review",
                         "producer": "match", "warning": "match"},
        "verdict": "review",
    },
    {
        "filename": "golden-hour-nonbold.jpg", "applicant": "Golden Hour Liqueurs", "beverage": "Distilled Spirits",
        "app": {"brand": "Golden Hour", "classType": "Orange Liqueur",
                  "abv": "24%", "net": "500 mL", "producer": "Golden Hour Liqueurs, Sonoma, CA", "origin": None, "warning": True},
        "label": {"brand": "Golden Hour", "classType": "Orange Liqueur",
                   "abv": "24% Alc./Vol. (48 Proof)", "net": "500 mL",
                   "producer": "Golden Hour Liqueurs, Sonoma, CA", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": False},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "review"},
        "verdict": "review",
    },
    {
        "filename": "ember-line-heavyblur.jpg", "applicant": "Ember Line Works", "beverage": "Distilled Spirits",
        "app": {"brand": "Ember Line", "classType": "Single Malt Whiskey",
                  "abv": "58.4%", "net": "700 mL", "producer": "Ember Line Works, Bend, OR", "origin": None, "warning": True},
        "label": {"brand": "Ember Line", "classType": "Single Malt Whiskey",
                   "abv": "ILLEGIBLE", "net": "700 mL",
                   "producer": "Ember Line Works, Bend, OR", "origin": None,
                   "warningPresent": True, "warningBody": "ILLEGIBLE", "warningHeaderCase": None, "warningHeaderBold": None},
        "quality": "heavyBlur", "illegible": ["abv", "warning"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "fail", "net": "match",
                         "producer": "match", "warning": "fail"},
        "verdict": "fail",
    },
    {
        "filename": "stillwater-glare.jpg", "applicant": "Stillwater Landing", "beverage": "Wine",
        "app": {"brand": "Stillwater Landing", "classType": "Finger Lakes Dry Riesling",
                  "abv": "11.5%", "net": "750 mL", "producer": "Stillwater Landing, Geneva, NY", "origin": None, "warning": True},
        "label": {"brand": "Stillwater Landing", "classType": "Finger Lakes Dry Riesling",
                   "abv": "ILLEGIBLE", "net": "750 mL",
                   "producer": "Stillwater Landing, Geneva, NY", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "glare", "illegible": ["abv"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "fail", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "red-kite-pixel.jpg", "applicant": "Red Kite Brewing", "beverage": "Malt Beverage",
        "app": {"brand": "Red Kite", "classType": "American Pale Ale",
                  "abv": "5.2%", "net": "16 FL OZ", "producer": "Red Kite Brewing, Fort Collins, CO", "origin": None, "warning": True},
        "label": {"brand": "Red Kite", "classType": "ILLEGIBLE",
                   "abv": "5.2% Alc./Vol.", "net": "16 FL OZ",
                   "producer": "Red Kite Brewing, Fort Collins, CO", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "pixelated", "illegible": ["classType"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "fail", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "casa-luz-origin.jpg", "applicant": "Casa Luz Selections", "beverage": "Distilled Spirits",
        "app": {"brand": "Casa Luz", "classType": "100% de Agave Blanco Tequila",
                  "abv": "40%", "net": "750 mL", "producer": "Casa Luz Selections, San Antonio, TX",
                  "origin": "Product of Mexico", "warning": True},
        "label": {"brand": "Casa Luz", "classType": "100% de Agave Blanco Tequila",
                   "abv": "40% Alc./Vol. (80 Proof)", "net": "750 mL",
                   "producer": "Casa Luz Selections, San Antonio, TX", "origin": "Product of Mexico",
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "origin": "match", "warning": "match"},
        "verdict": "match",
    },
    {
        "filename": "fogbank-dark.jpg", "applicant": "Fogbank Brewing", "beverage": "Malt Beverage",
        "app": {"brand": "Fogbank", "classType": "Baltic Porter",
                  "abv": "8.1%", "net": "500 mL", "producer": "Fogbank Brewing, Duluth, MN", "origin": None, "warning": True},
        "label": {"brand": "Fogbank", "classType": "Baltic Porter",
                   "abv": "8.1% Alc./Vol.", "net": "500 mL",
                   "producer": "Fogbank Brewing, Duluth, MN", "origin": None,
                   "warningPresent": True, "warningBody": "ILLEGIBLE", "warningHeaderCase": None, "warningHeaderBold": None},
        "quality": "dark", "illegible": ["warning"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "fail"},
        "verdict": "fail",
    },
    {
        "filename": "pilgrim-oak-damaged.jpg", "applicant": "Pilgrim Oak Cider Works", "beverage": "Distilled Spirits",
        "app": {"brand": "Pilgrim Oak", "classType": "Apple Brandy",
                  "abv": "42%", "net": "375 mL", "producer": "Pilgrim Oak Cider Works, Hood River, OR", "origin": None, "warning": True},
        "label": {"brand": "Pilgrim Oak", "classType": "Apple Brandy",
                   "abv": "42% Alc./Vol. (84 Proof)", "net": "375 mL",
                   "producer": "ILLEGIBLE", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "damaged", "illegible": ["producer"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "fail", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "tallgrass-cropped.jpg", "applicant": "Tallgrass Union", "beverage": "Malt Beverage",
        "app": {"brand": "Tallgrass Union", "classType": "Saison",
                  "abv": "6.4%", "net": "750 mL", "producer": "Tallgrass Union, Lawrence, KS", "origin": None, "warning": True},
        "label": {"brand": "Tallgrass Union", "classType": "Saison",
                   "abv": "6.4% Alc./Vol.", "net": "750 mL",
                   "producer": "Tallgrass Union, Lawrence, KS", "origin": None,
                   "warningPresent": True, "warningBody": "ILLEGIBLE", "warningHeaderCase": None, "warningHeaderBold": None},
        "quality": "cropped", "illegible": ["warning"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "fail"},
        "verdict": "fail",
    },
    {
        "filename": "maison-clair-angled.jpg", "applicant": "Clair Vineyard Selections", "beverage": "Wine",
        "app": {"brand": "Maison Clair", "classType": "Côtes de Provence Rosé",
                  "abv": "12.8%", "net": "750 mL", "producer": "Clair Vineyard Selections, Chicago, IL",
                  "origin": "Product of France", "warning": True},
        "label": {"brand": "Maison Clair", "classType": "Côtes de Provence Rosé",
                   "abv": "12.8% Alc./Vol.", "net": "750 mL",
                   "producer": "Clair Vineyard Selections, Chicago, IL", "origin": "Product of France",
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "angled", "illegible": [], "degraded": ["net"],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "review",
                         "producer": "match", "origin": "match", "warning": "match"},
        "verdict": "review",
    },
    {
        "filename": "blue-heron-blur.jpg", "applicant": "Blue Heron Distilling", "beverage": "Distilled Spirits",
        "app": {"brand": "Blue Heron", "classType": "Straight Rye Whiskey",
                  "abv": "47%", "net": "750 mL", "producer": "Blue Heron Distilling, Chestertown, MD", "origin": None, "warning": True},
        "label": {"brand": "Blue Heron", "classType": "Straight Rye Whiskey",
                   "abv": "47% Alc./Vol. (94 Proof)", "net": "750 mL",
                   "producer": "Blue Heron Distilling, Chestertown, MD", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "blurry", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "match",
    },
    {
        "filename": "copper-kettle-pass.jpg", "applicant": "Copper Kettle Imports", "beverage": "Distilled Spirits",
        "app": {"brand": "Copper Kettle", "classType": "Blended Scotch Whisky",
                  "abv": "43%", "net": "1 L", "producer": "Copper Kettle Imports, Boston, MA",
                  "origin": "Product of Scotland", "warning": True},
        "label": {"brand": "Copper Kettle", "classType": "Blended Scotch Whisky",
                   "abv": "43% Alc./Vol. (86 Proof)", "net": "1 L",
                   "producer": "Copper Kettle Imports, Boston, MA", "origin": "Product of Scotland",
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "origin": "match", "warning": "match"},
        "verdict": "match",
    },
    {
        "filename": "wildvine-glare.jpg", "applicant": "Wildvine Cellars", "beverage": "Wine",
        "app": {"brand": "Wildvine", "classType": "Sonoma Coast Orange Wine",
                  "abv": "13.4%", "net": "750 mL", "producer": "Wildvine Cellars, Sebastopol, CA", "origin": None, "warning": True},
        "label": {"brand": "ILLEGIBLE", "classType": "Sonoma Coast Orange Wine",
                   "abv": "13.4% Alc./Vol.", "net": "750 mL",
                   "producer": "Wildvine Cellars, Sebastopol, CA", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "glare", "illegible": ["brand"], "degraded": [],
        "field_verdicts": {"brand": "fail", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "south-shoal-pixel.jpg", "applicant": "South Shoal Beverage", "beverage": "Malt Beverage",
        "app": {"brand": "South Shoal", "classType": "Flavored Malt Beverage",
                  "abv": "5.0%", "net": "12 FL OZ", "producer": "South Shoal Beverage, New Bedford, MA", "origin": None, "warning": True},
        "label": {"brand": "South Shoal", "classType": "Flavored Malt Beverage",
                   "abv": "5.0% Alc./Vol.", "net": "ILLEGIBLE",
                   "producer": "South Shoal Beverage, New Bedford, MA", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "pixelated", "illegible": ["net"], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "fail",
                         "producer": "match", "warning": "match"},
        "verdict": "fail",
    },
    {
        "filename": "abbey-row-pass.jpg", "applicant": "Abbey Row Brewing", "beverage": "Malt Beverage",
        "app": {"brand": "Abbey Row", "classType": "Belgian Style Dubbel",
                  "abv": "7.6%", "net": "330 mL", "producer": "Abbey Row Brewing, Kalamazoo, MI", "origin": None, "warning": True},
        "label": {"brand": "Abbey Row", "classType": "Belgian Style Dubbel",
                   "abv": "7.6% Alc./Vol.", "net": "330 mL",
                   "producer": "Abbey Row Brewing, Kalamazoo, MI", "origin": None,
                   "warningPresent": True, "warningBody": WARNING_VERBATIM, "warningHeaderCase": "upper", "warningHeaderBold": True},
        "quality": "normal", "illegible": [], "degraded": [],
        "field_verdicts": {"brand": "match", "classType": "match", "abv": "match", "net": "match",
                         "producer": "match", "warning": "match"},
        "verdict": "match",
    },
]

assert len(ROWS) == 25, f"expected 25 fixtures, got {len(ROWS)}"
assert len({r["filename"] for r in ROWS}) == 25, "duplicate filename"

manifest_filenames = {
    row["filename"]
    for row in csv.DictReader(
        (FIXTURES_DIR.parent.parent / "design_handoff_label_verification" / "fixtures-manifest.csv")
        .read_text()
        .splitlines()
    )
}
assert manifest_filenames == {r["filename"] for r in ROWS}, "filename set does not match the manifest"


def build_expectations() -> dict[str, Any]:
    return {row["filename"]: {k: v for k, v in row.items() if k != "filename"} for row in ROWS}


def build_applications_csv() -> str:
    header = [
        "filename", "brand_name", "class_type", "alcohol_content", "net_contents",
        "producer", "country_of_origin", "government_warning", "applicant",
    ]
    lines = [",".join(header)]
    for row in ROWS:
        app = row["app"]
        cells = [
            row["filename"],
            app["brand"],
            app["classType"],
            app["abv"],
            app["net"],
            app["producer"] or "",
            app["origin"] or "",
            "true" if app["warning"] else "false",
            row["applicant"],
        ]
        lines.append(",".join(f'"{c}"' if "," in c else c for c in cells))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    FIXTURES_DIR.mkdir(exist_ok=True)
    (FIXTURES_DIR / "expectations.json").write_text(
        json.dumps(build_expectations(), indent=2, ensure_ascii=False) + "\n"
    )
    (FIXTURES_DIR / "applications.csv").write_text(build_applications_csv())
    print(f"wrote {FIXTURES_DIR / 'expectations.json'}")
    print(f"wrote {FIXTURES_DIR / 'applications.csv'}")
