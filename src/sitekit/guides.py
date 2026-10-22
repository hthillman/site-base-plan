"""Guides: answer-first how-to pages, plain comparisons, and one page per state's
free parcel layer. Linked from the footer and listed in the sitemap.

Every claim here should be checkable: the parcel pages are generated from the
verified registry in data/parcels/, and the how-to pages describe the same public
sources the tool itself queries. No competitor names (see the FAQ voice rules).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

from .geocode import STATES
from .pages import REPO_URL, SITE_URL, layout

PUBLISHED = "2026-10-20"
UPDATED = "2026-10-20"
AUTHOR = {"@type": "Person", "name": "Hunter Hillman"}


@dataclass
class Guide:
    slug: str
    kind: str          # "howto" | "compare" | "explainer"
    title: str         # <title>
    h1: str
    description: str   # meta description
    answer: str        # the direct answer, shown first; plain text
    body: str          # HTML after the answer
    related: tuple[str, ...] = ()


def _abs(path: str) -> str:
    return f"{SITE_URL}{path}" if SITE_URL else path


def _cta(text: str = "Basesheet does all of this for any US address in about 30 seconds, free, with no account.") -> str:
    return f'<div class="cta"><p>{escape(text)}</p><a class="btn" href="/">Build a base plan</a></div>'


LIMITS = ('<p class="note">Everything here is planning-level public data. Confirm boundaries, topography, wetlands and '
          'flood status with a licensed surveyor and the right specialists before design decisions depend on them.</p>')


GUIDES: list[Guide] = [
    Guide(
        "site-base-plan-from-address", "howto",
        "How to make a site base plan from an address (free public data)",
        "How to make a site base plan from an address",
        "Step by step: build a planning-level site base plan from a street address using free public data for parcel lines, LiDAR contours, soils, flood zones, wetlands and aerial imagery.",
        "Find the parcel in your state or county parcel layer, download USGS 3DEP elevation for the area and generate contours, "
        "add FEMA flood zones, NWI wetlands, SSURGO soils and an aerial, then bring everything into CAD in the local State Plane "
        "coordinate system. Done by hand this takes one to three hours; the result is good for feasibility and concept work, not "
        "for construction documents.",
        """
<h2>What a base plan needs</h2>
<ul>
<li><b>Parcel line</b> and neighboring parcels, from the state or county assessor GIS layer (see <a href="/parcels">free parcel data by state</a>).</li>
<li><b>Topography</b>: contours and slope from USGS 3DEP elevation data (<a href="/guides/contours-for-a-property">how to get contours</a>).</li>
<li><b>Regulated areas</b>: FEMA flood zones and National Wetlands Inventory polygons.</li>
<li><b>Soils</b>: NRCS SSURGO map units and their drainage and hydrologic soil group.</li>
<li><b>Context</b>: road centerlines and names, and a recent aerial photo.</li>
</ul>
<h2>Steps, by hand</h2>
<ol>
<li><b>Locate the site.</b> Geocode the address and note the county. Pick the State Plane zone for that county; every layer has to end up in it.</li>
<li><b>Get the parcel.</b> Query the statewide or county parcel service for the polygon at the address, plus the parcels around it. Save as GeoJSON or shapefile.</li>
<li><b>Get elevation.</b> Download the best 3DEP DEM covering the parcel plus a buffer (100 ft is a good default) from the USGS National Map Downloader, reproject it to State Plane feet, and generate contours.</li>
<li><b>Get the overlays.</b> Clip FEMA's National Flood Hazard Layer, the NWI wetlands layer and SSURGO soils to the same extent.</li>
<li><b>Get an aerial.</b> Export a georeferenced image (World Imagery or USDA NAIP) for the extent.</li>
<li><b>Assemble.</b> Bring it all into CAD or GIS on sensible layers, add a north arrow, scale and a note that it's planning-level, and write down where each layer came from and how old it is.</li>
</ol>
<h2>Where it goes wrong</h2>
<ul>
<li>Layers in different coordinate systems or units (meters vs US survey feet vs international feet) that don't line up.</li>
<li>Assessor parcel lines treated as surveyed boundaries. They're often 5 to 50 ft off (<a href="/guides/assessor-parcel-lines-vs-legal-boundaries">why</a>).</li>
<li>Contours drawn tighter than the elevation data supports, which implies accuracy that isn't there.</li>
<li>No record of sources and dates, so nobody can tell later which layer was stale.</li>
</ul>
""",
        ("contours-for-a-property", "what-is-a-base-sheet", "base-plan-vs-boundary-survey"),
    ),
    Guide(
        "contours-for-a-property", "howto",
        "How to get contour lines for a property (free USGS LiDAR)",
        "How to get contour lines for a property",
        "Get free contour lines for any US property from USGS 3DEP LiDAR elevation data: where to download it, how to make contours in QGIS, which interval the data supports, and the limits.",
        "Download the USGS 3DEP elevation model for the property from the National Map Downloader (the 1 meter LiDAR DEM where it "
        "exists, otherwise the 1/3 arc-second, roughly 10 meter, DEM), reproject it to your State Plane zone in feet, and run a "
        "contour tool such as QGIS's Raster > Extraction > Contour. 1 meter LiDAR supports 1 to 2 ft contours in open ground; "
        "10 meter data supports about 5 ft.",
        """
<h2>Step by step</h2>
<ol>
<li>Open the <a href="https://apps.nationalmap.gov/downloader/" rel="noopener">USGS National Map Downloader</a> and zoom to the property.</li>
<li>Under Elevation Products (3DEP), check <b>1 meter DEM</b>. If nothing comes back, use <b>1/3 arc-second DEM</b>. Search, then download the GeoTIFF tile that covers the site.</li>
<li>In QGIS, open the tile and reproject it with Raster > Projections > Warp to your county's State Plane zone (feet). Clip it to the site plus a buffer.</li>
<li>3DEP elevations are in meters (NAVD88). For contours in feet, convert first with the Raster Calculator (multiply by 3.28084 for international feet, or 3.280833 for US survey feet).</li>
<li>Run Raster > Extraction > Contour with the interval you want, then export the lines to DXF or GeoJSON for CAD.</li>
</ol>
<h2>Which interval the data supports</h2>
<table><tr><th>Source DEM</th><th>Typical contour interval</th></tr>
<tr><td>1 m LiDAR (most of the US now)</td><td>1 to 2 ft in open ground</td></tr>
<tr><td>3 m (older LiDAR)</td><td>2 ft</td></tr>
<tr><td>1/3 arc-second, about 10 m</td><td>5 ft or more</td></tr></table>
<p>Drawing 1 ft contours from 10 m data produces neat-looking lines that are mostly interpolation. Basesheet raises the interval automatically when the data is coarse and says so on the drawing.</p>
<h2>Limits to know</h2>
<ul>
<li><b>Collection date.</b> Each LiDAR project has a date, sometimes ten or more years ago. Grading since then won't show.</li>
<li><b>Bare earth.</b> The DEM removes buildings and trees. Under dense canopy there are fewer ground returns, so accuracy drops.</li>
<li><b>Small features.</b> Curbs, walls, swales narrower than a couple of cells get smoothed away. Water surfaces are flattened.</li>
</ul>
<p>More on accuracy: <a href="/guides/lidar-contours-vs-survey-topo">LiDAR contours vs a topographic survey</a>.</p>
""",
        ("topography-into-sketchup", "lidar-contours-vs-survey-topo", "site-base-plan-from-address"),
    ),
    Guide(
        "parcel-boundary-into-autocad", "howto",
        "How to get assessor parcel lines into AutoCAD or Civil 3D (in the right coordinates)",
        "How to get assessor parcel lines into AutoCAD or Civil 3D",
        "Bring a property's parcel lines from county or state GIS into AutoCAD or Civil 3D in State Plane feet: where to get the data, MAPIMPORT for Civil 3D, a QGIS-to-DXF route for plain AutoCAD, and the unit traps.",
        "Download the parcel polygon from your state or county GIS (as a shapefile or GeoJSON), reproject it to your State Plane "
        "zone in feet, then import it: Civil 3D and Map 3D read shapefiles directly with MAPIMPORT; plain AutoCAD needs a DXF, "
        "which QGIS can export. Set the drawing units to match the zone's foot (US survey or international).",
        """
<h2>1. Get the parcel</h2>
<p>About 30 states publish a free statewide parcel layer; elsewhere it's the county assessor or GIS department. Start with
<a href="/parcels">free parcel data by state</a>. Most are ArcGIS REST services you can add to QGIS or ArcGIS Pro and export from.</p>
<h2>2. Put it in State Plane feet</h2>
<p>Parcel services usually serve Web Mercator or latitude/longitude. In QGIS, use Export > Save Features As and set the CRS to your
county's State Plane zone in feet (for example NAD83 / Washington South (ftUS)). Whether the zone uses <b>US survey feet</b> or
<b>international feet</b> depends on the state; the difference is about 2 ft per million, which shows up at State Plane coordinates.</p>
<h2>3. Import</h2>
<ul>
<li><b>Civil 3D or Map 3D:</b> run MAPIMPORT, choose the shapefile, and assign the coordinate system (MAPCSASSIGN) so it matches.</li>
<li><b>Plain AutoCAD:</b> AutoCAD can't read shapefiles, so export a DXF from QGIS (Save Features As > DXF) and INSERT or open it. Coordinates come through as-is.</li>
</ul>
<h2>Traps</h2>
<ul>
<li>Importing latitude/longitude by mistake gives a parcel a fraction of a unit wide near 0,0.</li>
<li>Drawing units left as inches or meters. Set UNITS to the matching foot before anything else.</li>
<li>Using the line as the property boundary. Assessor lines are for taxes and can be 5 to 50 ft off; see <a href="/guides/assessor-parcel-lines-vs-legal-boundaries">parcel lines vs legal boundaries</a>.</li>
</ul>
""",
        ("assessor-parcel-lines-vs-legal-boundaries", "site-base-plan-from-address", "topography-into-sketchup"),
    ),
    Guide(
        "topography-into-sketchup", "howto",
        "How to get real topography into SketchUp (LiDAR terrain, not the coarse default)",
        "How to get real topography into SketchUp",
        "Three ways to get site terrain into SketchUp: built-in geo-location terrain, contours plus Sandbox From Contours, and importing a textured LiDAR terrain mesh. Which to use and why to keep the model near the origin.",
        "For design work, use real LiDAR terrain: either import contour lines (DXF) and build a surface with Sandbox > From "
        "Contours, or import a ready-made terrain mesh as COLLADA (.dae) with File > Import. Keep the model near the origin, "
        "because SketchUp loses precision at State Plane coordinates in the millions. SketchUp's own geo-location terrain is "
        "fine for context but too coarse for grading.",
        """
<h2>Option 1: geo-location terrain (quick, coarse)</h2>
<p>File > Geo-location > Add Location imports an aerial and a terrain patch. It's fast and good for context and massing, but the
terrain is coarse and can't be trusted for grades, steps or drainage.</p>
<h2>Option 2: contours + Sandbox</h2>
<ol>
<li>Make contours from USGS 3DEP data (<a href="/guides/contours-for-a-property">how</a>) and export them as DXF with elevations.</li>
<li>Move them near 0,0 before importing (or import into a CAD file and move there).</li>
<li>Import the DXF (SketchUp Pro), select the contours and run Draw > Sandbox > From Contours.</li>
</ol>
<p>Works well, but dense contours make a heavy mesh, and you'll need to drape the aerial yourself.</p>
<h2>Option 3: import a terrain mesh</h2>
<p>A COLLADA (.dae) mesh built straight from the DEM, with the aerial already applied as a texture, imports with File > Import
in any desktop SketchUp. This is what Basesheet produces as <code>terrain.dae</code>, already shifted near the origin with the
parcel line on it and the existing buildings as simple 3D blocks at their estimated heights, plus a
<code>site-local.dxf</code> in the same coordinates for linework.</p>
<h2>Why near the origin</h2>
<p>State Plane coordinates are millions of feet from 0,0. SketchUp works in single-precision for display, so geometry that far
out jitters and faces fail to form. Record the offset you subtract so you can put things back in CAD.</p>
""",
        ("contours-for-a-property", "parcel-boundary-into-autocad", "lidar-contours-vs-survey-topo"),
    ),
    Guide(
        "is-property-in-flood-zone", "howto",
        "How to check if a property is in a FEMA flood zone (and what the zones mean)",
        "How to check if a property is in a FEMA flood zone",
        "Check any US property's FEMA flood zone for free with the Flood Map Service Center or National Flood Hazard Layer, and what zones A, AE, VE, X and D mean for a site.",
        "Search the address in FEMA's Flood Map Service Center (msc.fema.gov) or the National Flood Hazard Layer viewer. Zones "
        "starting with A or V (A, AE, AH, AO, VE) are the Special Flood Hazard Area, the 1 percent annual chance or \"100-year\" "
        "floodplain. Shaded X is the 0.2 percent (\"500-year\") area, unshaded X is minimal hazard, and D means not studied.",
        """
<h2>Step by step</h2>
<ol>
<li>Go to <a href="https://msc.fema.gov/portal/home" rel="noopener">FEMA's Flood Map Service Center</a> and search the address.</li>
<li>Open the dynamic map (National Flood Hazard Layer) to see zone boundaries over the parcel, or view the effective FIRM panel.</li>
<li>Note the zone, the Base Flood Elevation (BFE) if shown, the panel number and its effective date.</li>
<li>Check for Letters of Map Change (LOMA/LOMR) on the parcel, and for preliminary maps that may replace the effective ones.</li>
</ol>
<h2>What the zones mean</h2>
<table><tr><th>Zone</th><th>Meaning</th></tr>
<tr><td>A, AE, AH, AO</td><td>Special Flood Hazard Area: 1% annual chance flood. AE has a BFE; A doesn't.</td></tr>
<tr><td>V, VE</td><td>Coastal high hazard area with wave action. Strictest rules.</td></tr>
<tr><td>X (shaded)</td><td>0.2% annual chance flood, or 1% with depths under 1 ft.</td></tr>
<tr><td>X (unshaded)</td><td>Minimal flood hazard.</td></tr>
<tr><td>D</td><td>Possible but undetermined hazard; not studied.</td></tr></table>
<h2>For site design</h2>
<ul>
<li>A line on a map isn't a line on the ground. Near the boundary, the actual ground elevation versus the BFE decides, which needs a survey (an Elevation Certificate).</li>
<li>Local floodplain codes are often stricter than FEMA minimums: fill limits, freeboard, compensatory storage.</li>
<li>Unmapped doesn't mean dry. Small streams and local drainage problems often aren't on FIRMs.</li>
</ul>
""",
        ("wetlands-on-a-property", "soil-data-for-a-site", "site-base-plan-from-address"),
    ),
    Guide(
        "wetlands-on-a-property", "howto",
        "How to check a property for wetlands (NWI) and what the map can't tell you",
        "How to check a property for wetlands",
        "Screen any US property for wetlands with the USFWS National Wetlands Inventory mapper, read NWI codes like PFO1A, and know why NWI is a screening map, not a delineation.",
        "Look up the property in the USFWS National Wetlands Inventory (NWI) Wetlands Mapper. NWI polygons show mapped wetlands and "
        "deepwater habitat with a code describing the type (PFO1A is a seasonally wet forested wetland, for example). NWI is a "
        "screening tool from aerial photo interpretation: it misses many small and forested wetlands and has no regulatory "
        "standing. Only a field delineation by a qualified wetland professional establishes where a regulated wetland is.",
        """
<h2>Step by step</h2>
<ol>
<li>Open the <a href="https://www.fws.gov/program/national-wetlands-inventory/wetlands-mapper" rel="noopener">NWI Wetlands Mapper</a> and search the address.</li>
<li>Click any polygon on or near the parcel to see its code and the source imagery date.</li>
<li>Also check SSURGO soils for <b>hydric soils</b> (<a href="/guides/soil-data-for-a-site">soil data</a>) and nearby streams. Hydric soil with no NWI polygon is a reason to look closer.</li>
<li>Check your state or county wetland inventory; some are more detailed than NWI.</li>
</ol>
<h2>Reading an NWI code</h2>
<p><code>PFO1A</code>: <b>P</b>alustrine (inland, non-tidal), <b>FO</b> forested, <b>1</b> broad-leaved deciduous, <b>A</b> temporarily flooded.
<code>PEM1C</code> is a seasonally flooded emergent (marsh) wetland. <code>R</code> codes are rivers, <code>L</code> lakes, <code>E</code> estuarine.</p>
<h2>Why it matters for a site</h2>
<ul>
<li>Regulated wetlands come with buffers set by local critical areas codes, often 50 to 200+ ft, which can take a big share of a small lot.</li>
<li>Jurisdiction can sit with the Army Corps of Engineers, the state and the local government at once.</li>
<li>Budget for a delineation early on any site with NWI polygons, hydric soils or a stream nearby.</li>
</ul>
""",
        ("is-property-in-flood-zone", "soil-data-for-a-site", "site-base-plan-from-address"),
    ),
    Guide(
        "soil-data-for-a-site", "howto",
        "How to find soil data for a site (Web Soil Survey, SSURGO) and what's useful for design",
        "How to find soil data for a site",
        "Find free soil data for any US site with NRCS Web Soil Survey (SSURGO): map units, hydrologic soil group, drainage class, depth to water table, and what the data can and can't tell you.",
        "Use the NRCS Web Soil Survey: draw an area of interest around the site and open the Soil Map tab to see SSURGO map units. "
        "For site design the most useful ratings are hydrologic soil group (A to D, for stormwater), drainage class, depth to "
        "water table and hydric rating. SSURGO is mapped at roughly 1:12,000 to 1:24,000, so it describes the area, not a "
        "specific spot; it doesn't replace a geotechnical report or infiltration test.",
        """
<h2>Step by step</h2>
<ol>
<li>Open <a href="https://websoilsurvey.nrcs.usda.gov/" rel="noopener">Web Soil Survey</a>, search the address and draw an Area of Interest around the parcel.</li>
<li>Soil Map tab: note each map unit symbol and name and how much of the site it covers.</li>
<li>Soil Data Explorer > Suitabilities and Limitations: run Hydrologic Soil Group, Drainage Class, Depth to Water Table and Hydric Rating.</li>
<li>Download the report as a PDF for the project file.</li>
</ol>
<h2>What matters for design</h2>
<table><tr><th>Rating</th><th>Why you care</th></tr>
<tr><td>Hydrologic soil group (A, B, C, D)</td><td>Runoff and infiltration potential. A drains well; D barely infiltrates. Drives stormwater approach.</td></tr>
<tr><td>Drainage class</td><td>Wet soils limit basements, pavements and plantings.</td></tr>
<tr><td>Depth to water table</td><td>Affects infiltration facilities, foundations and tree selection.</td></tr>
<tr><td>Hydric rating</td><td>A wetland indicator (see <a href="/guides/wetlands-on-a-property">wetlands</a>).</td></tr></table>
<h2>Limits</h2>
<ul>
<li>Map units include other soils (inclusions) that aren't drawn separately.</li>
<li>Urban areas are often mapped as "Urban land" complexes with little detail, since soils were disturbed.</li>
<li>For infiltration design or foundations, you'll still need test pits, infiltration tests or a geotechnical report.</li>
</ul>
""",
        ("wetlands-on-a-property", "is-property-in-flood-zone", "site-base-plan-from-address"),
    ),
    Guide(
        "what-is-a-base-sheet", "explainer",
        "What is a base sheet (base plan) in landscape architecture and site design?",
        "What is a base sheet?",
        "A base sheet, or base plan, is the existing-conditions drawing every site design is built on. What goes in one, where the data comes from (survey vs public GIS), and how offices use it.",
        "A base sheet (also called a base plan or existing-conditions plan) is the drawing that shows what's on and around a site "
        "before design starts: property lines, topography, buildings, roads, utilities, vegetation and regulated areas such as "
        "floodplain and wetlands. Every design sheet (layout, grading, planting, irrigation) references it, usually as an Xref in "
        "CAD. It comes either from a survey or, for early planning, from public GIS data.",
        """
<h2>What's on it</h2>
<ul>
<li>Property lines, easements and rights-of-way</li>
<li>Topography: contours and spot elevations</li>
<li>Existing structures, paving, walls and fences</li>
<li>Roads, curbs and driveways</li>
<li>Utilities (from the survey and locates)</li>
<li>Trees and vegetation</li>
<li>Regulated areas: floodplain, wetlands and buffers, steep slopes</li>
<li>North arrow, scale, sources and date</li>
</ul>
<h2>Survey base vs GIS base</h2>
<p>A surveyed base is the legal and dimensional record you build construction documents on. A GIS base, assembled from public
parcel, LiDAR, soils, flood and wetland data, is faster and free, and is what most offices use for feasibility, proposals and
concept design before a survey is ordered. See <a href="/guides/base-plan-vs-boundary-survey">base plan vs survey</a>.</p>
<h2>How offices use it</h2>
<ul>
<li>Kept in one CAD file and referenced into every design sheet, so updates flow through.</li>
<li>Layered to an office standard or the US National CAD Standard, so linework prints and turns off predictably.</li>
<li>Drawn in real-world coordinates (State Plane) so it lines up with civil and survey files later.</li>
</ul>
""",
        ("site-base-plan-from-address", "base-plan-vs-boundary-survey", "parcel-boundary-into-autocad"),
    ),
    Guide(
        "base-plan-vs-boundary-survey", "compare",
        "Public-data base plan vs a boundary survey: when you need which",
        "Public-data base plan vs a boundary survey",
        "When a free planning-level base plan from public GIS data is enough, and when you need a boundary or topographic survey from a licensed surveyor.",
        "A public-data base plan is enough for feasibility, proposals, concept design and site visit prep. You need a survey by a "
        "licensed land surveyor once anything depends on the exact boundary or exact grades: permit submittals that require one, "
        "building or grading near setbacks or property lines, fences and walls on the line, construction documents, and any "
        "dispute.",
        """
<h2>Side by side</h2>
<table><tr><th></th><th>Public-data base plan</th><th>Boundary / topographic survey</th></tr>
<tr><td>Source</td><td>Assessor parcels, USGS LiDAR, FEMA, NWI, SSURGO</td><td>Field measurement, deed and plat research, monuments</td></tr>
<tr><td>Boundary accuracy</td><td>Often 5 to 50 ft off</td><td>Legal boundary, to hundredths of a foot</td></tr>
<tr><td>Topography</td><td>LiDAR, about 10 cm vertical in open ground, dated</td><td>Current, with curbs, walls and breaklines</td></tr>
<tr><td>Legal standing</td><td>None</td><td>Stamped, recordable</td></tr>
<tr><td>Time</td><td>Minutes</td><td>Days to weeks</td></tr>
<tr><td>Cost</td><td>Free</td><td>Varies widely with site and scope</td></tr></table>
<h2>A public-data base plan is fine for</h2>
<ul><li>Is this site worth pursuing? Rough buildable area and constraints</li><li>Fee proposals and scoping</li>
<li>Concept and schematic options</li><li>Planning a site visit</li><li>Deciding what survey scope to order</li></ul>
<h2>Order a survey when</h2>
<ul><li>A permit or lender requires one</li><li>Anything is placed near a setback or the property line</li>
<li>Grading, drainage or walls need real spot elevations</li><li>You're producing construction documents</li>
<li>There's any question about where the line is</li></ul>
<p>Types to know: a <b>boundary survey</b> establishes the lines; a <b>topographic survey</b> adds elevations and features; an
<b>ALTA/NSPS Land Title Survey</b> is the detailed standard for commercial transactions.</p>
""",
        ("assessor-parcel-lines-vs-legal-boundaries", "lidar-contours-vs-survey-topo", "what-is-a-base-sheet"),
    ),
    Guide(
        "lidar-contours-vs-survey-topo", "compare",
        "How accurate are LiDAR contours? USGS 3DEP vs a topographic survey",
        "LiDAR contours vs a topographic survey",
        "How accurate free USGS 3DEP LiDAR contours are compared with a surveyed topo: vertical accuracy specs, where LiDAR falls short (trees, small features, age), and when it's good enough.",
        "Modern USGS 3DEP LiDAR (Quality Level 2 or better) is specified to about 10 cm (4 in) vertical accuracy in open, "
        "non-vegetated ground, which makes it good for 1 to 2 ft contours and early grading studies. It's weaker under dense "
        "vegetation, smooths out curbs, walls and narrow swales, and is only as current as its collection date. A topographic "
        "survey adds exact spot elevations on hard surfaces and breaklines, which you need for detailed grading and drainage.",
        """
<h2>Side by side</h2>
<table><tr><th></th><th>3DEP LiDAR DEM</th><th>Topographic survey</th></tr>
<tr><td>Vertical accuracy</td><td>About 10 cm RMSE in open ground (QL2); worse under canopy</td><td>Typically a few hundredths of a foot on hard surfaces</td></tr>
<tr><td>Detail</td><td>1 m grid; features narrower than a couple of meters smoothed</td><td>Breaklines at curbs, walls, top and toe of slope</td></tr>
<tr><td>Currency</td><td>Collection date, sometimes 10+ years old</td><td>Current</td></tr>
<tr><td>Buildings, trees</td><td>Removed (bare earth)</td><td>Located, with finished floors and tree sizes</td></tr></table>
<h2>Good enough for</h2>
<ul><li>Overall slope, drainage direction and steep areas</li><li>Siting buildings, parking and paths at concept level</li>
<li>Rough cut and fill comparisons between options</li></ul>
<h2>Not good enough for</h2>
<ul><li>ADA routes, curb and gutter, finished floor tie-ins</li><li>Wall heights and stair counts</li><li>Detailed drainage near buildings</li></ul>
<p>Always check the collection date and resolution. Basesheet records both in each download's provenance file and widens the
contour interval when the data is coarse. See <a href="/guides/contours-for-a-property">how to get contours</a>.</p>
""",
        ("contours-for-a-property", "base-plan-vs-boundary-survey", "topography-into-sketchup"),
    ),
    Guide(
        "assessor-parcel-lines-vs-legal-boundaries", "compare",
        "Why GIS parcel lines don't match property boundaries (assessor parcels vs legal boundaries)",
        "Assessor parcel lines vs legal boundaries",
        "Why county GIS parcel lines are often 5 to 50 ft off the real property line, how to spot a bad one, and what actually defines a legal boundary.",
        "County and state GIS parcel lines come from assessor tax maps, drawn to value and bill property, not to locate it. They're "
        "digitized from deeds and plats with varying care and are commonly 5 to 50 ft off, more in rural areas. The legal boundary "
        "is defined by the deed or recorded plat and the monuments on the ground, as retraced by a licensed land surveyor.",
        """
<h2>Why they're off</h2>
<ul>
<li>Tax maps were often drafted by hand from deed descriptions and later digitized, carrying old errors forward.</li>
<li>Many were fitted to older aerials or road centerlines rather than survey control.</li>
<li>Deed descriptions themselves can conflict, overlap or leave gaps.</li>
<li>One tax parcel can cover several legal lots, and one lot can be split across parcels.</li>
<li>Easements and rights-of-way are often missing or approximate.</li>
</ul>
<h2>How to sanity-check one</h2>
<ul>
<li>Overlay it on a current aerial. Fences, hedges and driveways that run consistently offset from the line suggest a shift.</li>
<li>Compare the drawn dimensions with the recorded plat or deed.</li>
<li>Look for a recorded survey of the property at the county recorder or surveyor's office.</li>
<li>Check neighbors: if every parcel on the block is shifted the same way, it's the map.</li>
</ul>
<h2>What it's still useful for</h2>
<p>Approximate lot size and shape, frontage, neighbors, and a first look at setbacks and buildable area. Anything near the line
needs a survey. See <a href="/guides/base-plan-vs-boundary-survey">base plan vs survey</a> and
<a href="/parcels">free parcel data by state</a>.</p>
""",
        ("base-plan-vs-boundary-survey", "parcel-boundary-into-autocad", "site-base-plan-from-address"),
    ),
]
BY_SLUG = {g.slug: g for g in GUIDES}


def _article_ld(path: str, headline: str, description: str) -> dict:
    return {"@context": "https://schema.org", "@type": "TechArticle", "headline": headline, "description": description,
            "datePublished": PUBLISHED, "dateModified": UPDATED, "author": AUTHOR, "inLanguage": "en-US",
            "mainEntityOfPage": _abs(path), "isPartOf": {"@type": "WebSite", "name": "Basesheet", "url": _abs("/")}}


def _crumbs_ld(items: list[tuple[str, str]]) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": _abs(p)} for i, (n, p) in enumerate(items)]}


def guide_page(slug: str) -> str | None:
    g = BY_SLUG.get(slug)
    if not g:
        return None
    path = f"/guides/{g.slug}"
    related = "".join(f'<li><a href="/guides/{r}">{escape(BY_SLUG[r].h1)}</a></li>' for r in g.related if r in BY_SLUG)
    body = f"""
<p class="crumbs"><a href="/guides">Guides</a></p>
<h1>{escape(g.h1)}</h1>
<p class="answer">{escape(g.answer)}</p>
{g.body}
{LIMITS}
{_cta()}
{f'<h2>Related</h2><ul>{related}</ul>' if related else ''}
<p class="note">Updated October 2026.</p>
"""
    return layout(f"{g.title} · Basesheet", path, body, description=g.description,
                  jsonld=[_article_ld(path, g.h1, g.description), _crumbs_ld([("Guides", "/guides"), (g.h1, path)])])


# ---- Parcel data by state ---------------------------------------------------

def state_slug(code: str) -> str:
    return re.sub(r"[^a-z]+", "-", STATES.get(code, code).lower()).strip("-")


def _slug_to_code() -> dict[str, str]:
    return {state_slug(c): c for c in STATES}


def _field_list(s) -> list[str]:
    out = []
    if s.apn_fields:
        out.append("parcel number (" + ", ".join(s.apn_fields) + ")")
    if s.situs_field:
        out.append(f"site address ({s.situs_field})")
    if s.owner_field:
        out.append(f"owner ({s.owner_field})")
    if s.deed_book_field or s.deed_ref_field:
        out.append("deed reference")
    if s.plat_book_field or s.plat_ref_field:
        out.append("plat reference")
    if s.legal_field:
        out.append("legal description")
    if s.subdivision_field:
        out.append("subdivision")
    return out


def _source_table(s) -> str:
    v = s.verified or {}
    rows = [("Layer", escape(s.name)), ("Publisher", escape(s.publisher)), ("Coverage", escape(s.coverage or "Statewide")),
            ("Data vintage", escape(s.vintage or "Not stated")), ("Terms", escape(s.terms or "Not stated")),
            ("Fields", escape("; ".join(_field_list(s)) or "Geometry only")),
            ("Not published", escape(", ".join(s.unpublished()) or "Nothing; owner, deed and plat references are all included")),
            ("REST endpoint", f'<code>{escape(s.url)}</code>'),
            ("Last verified", escape(f"{v.get('date', '')} with a live point and parcel-number query" if v.get("date") else "Not recorded"))]
    return '<div class="tablewrap"><table>' + "".join(f"<tr><th>{a}</th><td>{b}</td></tr>" for a, b in rows) + "</table></div>"


HOW_TO_USE = """
<h2>How to use it</h2>
<ul>
<li><b>QGIS:</b> Layer > Data Source Manager > ArcGIS REST Server, add a connection with the service URL (the endpoint above without the
final <code>/0</code>), then add the layer. Filter to your area before exporting.</li>
<li><b>ArcGIS Pro:</b> Add Data > Data From Path, paste the endpoint.</li>
<li><b>Direct query:</b> append <code>/query?geometry=LON,LAT&amp;geometryType=esriGeometryPoint&amp;inSR=4326&amp;spatialRel=esriSpatialRelIntersects&amp;outFields=*&amp;f=geojson</code> to get the parcel at a point.</li>
<li><b>CAD:</b> see <a href="/guides/parcel-boundary-into-autocad">getting a parcel into AutoCAD or Civil 3D</a>.</li>
</ul>
"""


def parcel_state_page(slug: str) -> str | None:
    from .parcel import all_sources, county_sources

    code = _slug_to_code().get(slug)
    if not code or (code not in all_sources() and code not in county_sources()):
        return None
    name = STATES[code]
    path = f"/parcels/{slug}"
    s = all_sources().get(code)
    counties = county_sources().get(code, {})
    if s:
        answer = (f"Yes. {name} publishes a free statewide parcel layer: {s.name}, from {s.publisher}. "
                  f"Coverage: {(s.coverage or 'statewide').split('. Missing')[0].rstrip('.')}. It's a public ArcGIS REST service with no API key or login.")
        notes = f'<h2>Notes for GIS users</h2><p>{escape(s.notes)}</p>' if s.notes else ""
        detail = f"<h2>The layer</h2>{_source_table(s)}{notes}{HOW_TO_USE}"
        desc = (f"Free {name} parcel data: the statewide {s.publisher.split(' (')[0]} layer, coverage ({s.coverage or 'statewide'}), "
                f"vintage, fields and REST endpoint, verified {(s.verified or {}).get('date', '')}.")
    elif counties:
        listed = sorted(counties.values(), key=lambda c: c.county)
        answer = (f"{name} has no single free statewide parcel layer we could verify, but many counties publish their own. "
                  f"Basesheet currently uses {len(listed)} {name} county services: "
                  + ", ".join(c.county for c in listed) + ".")
        detail = "<h2>County layers</h2>" + "".join(
            f"<h3>{escape(c.county)} County</h3>{_source_table(c)}" + (f'<p class="note">{escape(c.notes)}</p>' if c.notes else "")
            for c in listed) + HOW_TO_USE
        desc = f"Free {name} parcel data by county: {len(listed)} county GIS parcel services with coverage, vintage, fields and REST endpoints."
    body = f"""
<p class="crumbs"><a href="/parcels">Parcel data by state</a></p>
<h1>Free parcel data in {escape(name)}</h1>
<p class="answer">{escape(answer)}</p>
{detail}
<p class="note">Assessor parcel lines are for taxation and are often 5 to 50 ft off the legal boundary.
<a href="/guides/assessor-parcel-lines-vs-legal-boundaries">Why</a>.</p>
{_cta(f"Basesheet uses this to draw the parcel line on a base plan for any {name} address, with LiDAR contours, soils, flood zones and wetlands." if (s or counties) else f"Basesheet still builds a base plan for any {name} address, with contours, soils, flood zones and wetlands; it just can't draw the parcel line.")}
"""
    title = f"{name} parcel data: free statewide GIS layer and REST endpoint" if s else f"{name} parcel data: where to get it free"
    return layout(f"{title} · Basesheet", path, body, description=desc,
                  jsonld=[_article_ld(path, f"Free parcel data in {name}", desc),
                          _crumbs_ld([("Parcel data by state", "/parcels"), (name, path)])])


def parcels_index() -> str:
    from .parcel import all_sources, county_sources

    src, cs = all_sources(), county_sources()
    have = sorted(set(src) | set(cs), key=lambda c: STATES.get(c, c))
    rows = "".join(
        f'<tr><td><a href="/parcels/{state_slug(c)}">{escape(STATES.get(c, c))}</a></td>'
        f'<td>{escape(src[c].coverage if c in src else f"{len(cs[c])} counties")}</td>'
        f'<td>{escape(src[c].vintage if c in src else "County layers")}</td></tr>' for c in have)
    missing = sorted((c for c in STATES if c not in have), key=lambda c: STATES[c])
    miss = ", ".join(escape(STATES[c]) for c in missing)
    body = f"""
<h1>Free parcel data by state</h1>
<p class="answer">{len(src)} states publish a free statewide parcel layer that works without an API key or login, and some others
have free county layers. Each page below lists the publisher, coverage, data vintage, which fields are included, the REST
endpoint and when it was last verified with a live query.</p>
<div class="tablewrap"><table><tr><th>State</th><th>Coverage</th><th>Vintage</th></tr>{rows}</table></div>
<h2>No free statewide layer found yet</h2>
<p>{miss}.</p>
<p class="note">In these states parcel data comes from each county's assessor or GIS department, and some charge for it or require
an account. Basesheet still builds a base plan there, without the parcel line.</p>
<p class="note">This is the same registry Basesheet uses to draw parcel lines. It's open source; if you know a free service we're missing,
<a href="{REPO_URL}/blob/main/CONTRIBUTING.md">add it</a>.</p>
{_cta()}
"""
    desc = f"Free statewide parcel GIS layers for {len(src)} US states, with coverage, vintage, fields, REST endpoints and verification dates."
    return layout("Free parcel data by state (statewide GIS parcel layers) · Basesheet", "/parcels", body, description=desc,
                  jsonld=[_article_ld("/parcels", "Free parcel data by state", desc)])


def guides_index() -> str:
    def items(kind):
        return "".join(f'<li><a href="/guides/{g.slug}">{escape(g.h1)}</a></li>' for g in GUIDES if g.kind in kind)
    body = f"""
<h1>Guides</h1>
<p class="sub">Short, direct answers about getting site data from free public sources: what to download, how to use it, and how far to trust it.</p>
<h2>How to</h2><ul>{items(("howto", "explainer"))}</ul>
<h2>Know the limits</h2><ul>{items(("compare",))}</ul>
<h2>Data</h2><ul><li><a href="/parcels">Free parcel data by state</a></li><li><a href="/sources">Every data source Basesheet uses</a></li></ul>
"""
    return layout("Guides: site data from free public sources · Basesheet", "/guides", body,
                  description="How to get contours, parcel boundaries, flood zones, wetlands and soils for a property from free public data, and how accurate each one is.")


def all_paths() -> list[str]:
    from .parcel import all_sources, county_sources

    have = set(all_sources()) | set(county_sources())
    return (["/guides"] + [f"/guides/{g.slug}" for g in GUIDES] + ["/parcels"]
            + [f"/parcels/{state_slug(c)}" for c in sorted(have, key=lambda c: STATES.get(c, c))])
