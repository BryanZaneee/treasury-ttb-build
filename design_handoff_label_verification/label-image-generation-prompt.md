# Prompt: generate 25 COLA label specimen images

Copy everything below the line and hand it to your image-generation agent.

---

## Role

You are generating **synthetic photographic specimens of alcohol beverage labels** for a TTB-style label-verification test set. These are QA fixtures for an OCR/field-extraction pipeline — not marketing art. Realism of the *capture conditions* matters as much as the label design.

## Output spec

- 25 images, one per row in the table below, using the **exact filename** given (extension included).
- Aspect: portrait ~3:4 for wine/spirits labels, ~4:3 or square for malt beverage labels. Long edge 1200–1600 px.
- Each image is a **photo of a physical label** — either a flat label lying on a neutral surface, or applied to a bottle/can. Include realistic edges, paper texture, slight surface shadow. No pure-vector flat renders, no drop-shadowed "mockup" chrome, no watermarks, no borders added around the photo.
- No real brands, no real logos, no recognizable trade dress. Every brand below is fictional; keep it that way.
- No people, no glasses of drink, no props beyond the container itself.

## Text that MUST be legible and correct

For each row, the label must carry these fields, spelled exactly as written in the table:

1. **Brand name** (largest type on the label)
2. **Class / type** designation
3. **Alcohol content** string
4. **Net contents** string
5. **Bottler / producer / brewer statement**
6. **Country of origin** — only where the table lists one
7. **Government warning** — see below

Do not add extra fields, awards, medals, barcodes, QR codes, or invented tasting notes. A brief top line (e.g. "Est. 1889", "Small Batch") is allowed where the table gives one.

### Government warning — verbatim

Unless the row says otherwise, set this as small print, typically bottom of the label, header bold and in all caps:

> **GOVERNMENT WARNING:** (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.

Character-exact. Do not paraphrase, re-punctuate, or drop the numbering — except on the rows that explicitly call for a defect.

## Capture-quality treatments

Apply the treatment named in each row. These must be *photographically* real, not a CSS-style filter look:

| Treatment | What it should look like |
| --- | --- |
| `normal` | Even light, sharp, fully legible, slight natural texture |
| `blurry` | Mild focus miss — all text still readable but soft-edged |
| `heavyBlur` | Severe focus miss — brand readable in outline, small print not |
| `glare` | Hard specular highlight from a flash or window blowing out one region; the named field falls inside the blown area |
| `pixelated` | Low-resolution re-upload: visible blocky pixels and JPEG ringing; the named field is genuinely illegible |
| `angled` | Shot 30–45° off-axis with keystone distortion and falling focus on the far edge |
| `dark` | Underexposed, shadowed, muddy — small print sinks into the background |
| `damaged` | Torn corner, scuff, water stain, or peeling edge over part of the text |
| `cropped` | Frame cuts off part of the label so one required field is partially or wholly outside the image |

## Label art direction — rotate across these 8 looks

Assign the look listed in each row. Keep them visually distinct:

- **classic** — cream paper, thin gold rule, upright sans brand
- **crest** — double gold border, Garamond-style serif, wide letterspacing
- **minimal** — near-white, very wide letterspaced light sans, lots of air
- **band** — warm tan ground with a solid navy horizontal band
- **script** — soft warm paper, flowing calligraphic brand
- **industrial** — pale grey stock, heavy black rule, monospace/technical type
- **slate** — dark charcoal ground with cream ink and a brass rule
- **botanical** — cool pale green stock, sage rule, engraved-botanical feel

## The 25 specimens

Existing fixtures (rows 1–12) — filenames must match exactly.

| # | filename | brand | class / type | alcohol | net | producer / origin | look | treatment | intended defect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | old-tom-pass.png | OLD TOM DISTILLERY (top line: Est. 1889) | Kentucky Straight Bourbon Whiskey | 45% Alc./Vol. (90 Proof) | 750 mL | Bottled by Old Tom Distillery, Bardstown, KY | classic | normal | none — clean reference |
| 2 | stones-throw-caps.jpg | STONE'S THROW (Small Batch) | Kentucky Straight Bourbon Whiskey | 45% Alc./Vol. (90 Proof) | 750 mL | Bottled by Stone's Throw Spirits, Loretto, KY | industrial | normal | brand set in full caps |
| 3 | harbor-mist-nowarning.png | HARBOR MIST (Coastal Series) | India Pale Ale | 6.8% Alc./Vol. | 12 FL OZ | Brewed by Harbor Mist Brewing, Astoria, OR | botanical | normal | **government warning entirely absent** |
| 4 | cedar-ridge-titlecase.jpg | CEDAR RIDGE (Estate Grown) | Napa Valley Cabernet Sauvignon | 14.2% Alc./Vol. | 750 mL | Produced and bottled by Cedar Ridge Vineyards, Rutherford, CA | crest | normal | warning header reads "Government Warning:" in title case |
| 5 | lark-hollow-reworded.png | LARK HOLLOW (Pot Distilled) | Small Batch Gin | 44% Alc./Vol. (88 Proof) | 750 mL | Distilled by Lark Hollow Craft Spirits, Asheville, NC | minimal | normal | warning replaced with: "GOVERNMENT WARNING: Drinking alcohol may be harmful to your health. Please enjoy responsibly and never drink and drive." |
| 6 | vinos-del-sol-abv.jpg | VIÑOS DEL SOL (Denominación de Origen) | Rioja Tempranillo | 12.5% Alc./Vol. | 750 mL | Imported by Sol Selections, Miami, FL · Product of Spain | crest | normal | ABV differs from filing (12.5 vs 13.5) |
| 7 | iron-gate-blur.jpg | IRON GATE (Bottled in Bond) | Straight Rye Whiskey | 50% Alc./Vol. (100 Proof) | 750 mL | Bottled by Iron Gate Rye Works, Frederick, MD | band | blurry | soft capture, low confidence |
| 8 | saltmarsh-glare.jpg | SALTMARSH (Sour Program) | Gose Style Ale | 4.5% Alc./Vol. | 16 FL OZ | Brewed by Saltmarsh Brewing Union, Portland, ME | script | glare | **glare must land on net contents** — "16 FL OZ" unreadable |
| 9 | north-fen-pixel.png | NORTH FEN (Grain to Glass) | Vodka | 40% Alc./Vol. (80 Proof) | 1 L | Distilled by North Fen Vodka Co., Duluth, MN | slate | pixelated | **brand name illegible** |
| 10 | brasserie-verte-origin.jpg | BRASSERIE VERTE (Brassée en Belgique) | Belgian Style Tripel | 9.2% Alc./Vol. | 330 mL | Imported by Continental Beverage Imports, Newark, NJ | crest | angled | no country-of-origin statement anywhere on label |
| 11 | quarry-house-units.png | QUARRY HOUSE (Single Vineyard) | Willamette Valley Pinot Noir | 13.1% Alc./Vol. | 75 cl | Produced and bottled by Quarry House Cellars, Dundee, OR | minimal | normal | net contents in cl, filing says mL |
| 12 | golden-hour-nonbold.jpg | GOLDEN HOUR (Aperitivo) | Orange Liqueur | 24% Alc./Vol. (48 Proof) | 500 mL | Produced by Golden Hour Liqueurs, Sonoma, CA | script | normal | warning header not bold |

New fixtures (rows 13–25).

| # | filename | brand | class / type | alcohol | net | producer / origin | look | treatment | intended defect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13 | ember-line-heavyblur.jpg | EMBER LINE (Cask Strength) | Single Malt Whiskey | 58.4% Alc./Vol. (116.8 Proof) | 700 mL | Distilled by Ember Line Works, Bend, OR | slate | heavyBlur | small print unreadable — alcohol content and warning both unverifiable |
| 14 | stillwater-glare.jpg | STILLWATER LANDING (Estate Bottled) | Finger Lakes Dry Riesling | 11.5% Alc./Vol. | 750 mL | Produced and bottled by Stillwater Landing, Geneva, NY | botanical | glare | **glare across the alcohol content line** |
| 15 | red-kite-pixel.png | RED KITE (Hazy Series) | American Pale Ale | 5.2% Alc./Vol. | 16 FL OZ | Brewed by Red Kite Brewing, Fort Collins, CO | industrial | pixelated | **class/type designation illegible** |
| 16 | casa-luz-origin.jpg | CASA LUZ (Hecho en México) | 100% de Agave Blanco Tequila | 40% Alc./Vol. (80 Proof) | 750 mL | Imported by Casa Luz Selections, San Antonio, TX · Product of Mexico | band | normal | none — clean import reference |
| 17 | fogbank-dark.jpg | FOGBANK (Night Harvest) | Baltic Porter | 8.1% Alc./Vol. | 500 mL | Brewed by Fogbank Brewing, Duluth, MN | slate | dark | warning statement sinks into shadow |
| 18 | pilgrim-oak-damaged.jpg | PILGRIM OAK (Barrel No. 14) | Apple Brandy | 42% Alc./Vol. (84 Proof) | 375 mL | Distilled by Pilgrim Oak Cider Works, Hood River, OR | classic | damaged | tear removes the producer statement |
| 19 | tallgrass-cropped.png | TALLGRASS UNION (Farmhouse Series) | Saison | 6.4% Alc./Vol. | 750 mL | Brewed by Tallgrass Union, Lawrence, KS | minimal | cropped | frame cuts off the bottom — warning statement partly outside the image |
| 20 | maison-clair-angled.jpg | MAISON CLAIR (Mis en Bouteille au Domaine) | Côtes de Provence Rosé | 12.8% Alc./Vol. | 750 mL | Imported by Clair Vineyard Selections, Chicago, IL · Product of France | crest | angled | far edge out of focus; net contents borderline |
| 21 | blue-heron-blur.jpg | BLUE HERON (Coastal Reserve) | Straight Rye Whiskey | 47% Alc./Vol. (94 Proof) | 750 mL | Bottled by Blue Heron Distilling, Chestertown, MD | band | blurry | soft but readable |
| 22 | copper-kettle-pass.png | COPPER KETTLE (Est. 1974) | Blended Scotch Whisky | 43% Alc./Vol. (86 Proof) | 1 L | Imported by Copper Kettle Imports, Boston, MA · Product of Scotland | classic | normal | none — clean reference |
| 23 | wildvine-glare.jpg | WILDVINE (Skin Contact) | Sonoma Coast Orange Wine | 13.4% Alc./Vol. | 750 mL | Produced and bottled by Wildvine Cellars, Sebastopol, CA | script | glare | **glare across the brand name** |
| 24 | south-shoal-pixel.png | SOUTH SHOAL (Hard Seltzer Program) | Flavored Malt Beverage | 5.0% Alc./Vol. | 12 FL OZ | Brewed by South Shoal Beverage, New Bedford, MA | minimal | pixelated | **net contents illegible** |
| 25 | abbey-row-pass.jpg | ABBEY ROW (Bottle Conditioned) | Belgian Style Dubbel | 7.6% Alc./Vol. | 330 mL | Brewed by Abbey Row Brewing, Kalamazoo, MI | botanical | normal | none — clean reference |

## Distribution check before you deliver

- 11 clean captures, 2 mild blur, 1 heavy blur, 3 glare, 3 pixelated, 2 off-axis, 1 dark, 1 damaged, 1 cropped.
- Beverage mix: 10 distilled spirits, 7 wine, 8 malt beverage.
- All 8 label looks used at least twice.
- Every "illegible" field is *actually* illegible at full resolution; every other field on that same image is still readable.
- Return a manifest listing filename → brand, class/type, alcohol, net, origin, treatment, and which fields you made unreadable.
