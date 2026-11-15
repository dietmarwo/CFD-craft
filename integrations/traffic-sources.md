# Supplied street emissions

`traffic_sources.py` extends an existing case from the urban map converter. It
adds native line sources from a GeoJSON street network and an explicit CSV
rate table. Install the same optional Shapely dependency as for `urban_map.py`
(`integrations/requirements-urban.txt`); the Rust solver gains no dependency.
The tool never derives emissions from street type, road width, traffic counts
or an assumed default. Existing gas/particle constituents and sources remain
in the case.

The input GeoJSON must be a FeatureCollection of LineString or MultiLineString
features in the **same projected metric coordinate system** as the buildings.
A GeoJSON `crs` member that names geographic coordinates (for example CRS84)
is rejected (`streets.crs`); reproject first.
Street IDs come from Feature.id, or the `id` property when no feature ID is
present (`--street-id-property` changes the property name). Simultaneous IDs
must agree, and duplicates are errors. Polylines are split at every vertex;
a bend is never replaced by a straight chord. Coordinates may have finite Z
values, but these are explicitly replaced by the required `--height-m` above
the flattened ground. Their original Z ranges remain in provenance. This is
not terrain, bridge or tunnel modeling.

The required CSV columns are:

| Column | Meaning |
|---|---|
| `street_id` | Exact street ID after surrounding whitespace is stripped |
| `constituent` | An existing case constituent ID |
| `rate_kg_s_m` | Supplied finite nonnegative rate, in kg per second per meter |
| `units` | Exactly `kg/s/m`; missing or different units are rejected |

A row is unique per street/constituent pair. Different constituents may have
different rates on the same street. Unknown positive-rate street IDs are
errors. Unknown zero-rate rows and unlisted/unrated streets are explicitly
recorded, with no invented emissions. The committed synthetic CSV/GeoJSON
fixtures demonstrate the schema; their rates are synthetic test inputs.

The coordinate transformation is the one recorded in `map-provenance.json`:
clip in the original map crop, rotate by minus its stored angle about its
stored origin, translate, then clip to the native horizontal domain. Domain
upper bounds are exclusive, including source endpoints. A supplied positive
rate can consequently produce no source when its whole street lies outside
the crop/domain; its original and retained lengths and omission reason remain
in provenance. Original vertices, multiple parts, and duplicate/overlapping
street multiplicity are preserved as declared by the input.

Each retained straight segment emits its length multiplied by the supplied
rate. Per-street lengths, per-row emission totals and generated source IDs are
recorded in `traffic-provenance.json`, together with SHA-256 hashes of the
**consumed** street file, rate CSV, input case and map provenance. Source frame,
height, clipping and absent license/attribution declarations are explicit.
Optional `--street-license`, `--street-attribution` and `--rates-description`
record the source terms; they do not infer or change any rate.

A continuous segment that touches or crosses a building footprint at source
height is rejected with `CFD-M002`, the street/building IDs and segment. The
check covers the whole segment, including a narrow building between its
endpoints; it does not sample a few locations. Concave prism footprints are
used directly. Native `check` then evaluates the complete case, including its
cell-center solid mask: a coarse-grid `CFD-E040` rejection stays visible and
is not repaired by shifting or redistributing emissions.

Invoke `python integrations/traffic_sources.py` with `--case`,
`--map-provenance`, `--streets`, `--rates`, `--height-m`, `--output` and
optionally `--binary`. The output directory must be new. Success retains
`case.json`, `traffic-provenance.json`, `check.json` and `check.stderr`.
Rejections retain a coded `diagnostic.json`; native-check failures also retain
the converted case and provenance for inspection. The tool performs preflight,
not a flow simulation or experimental validation.

`validation/test_traffic_sources.py` verifies line-length/rate normalization,
coordinate rotation and clipping, multisegment bends, continuous prism
intersection, missing/invalid rates/units/IDs, native-mask rejection, and CLI
checks under normal Python and `python -O`. A small native transport fixture
independently verifies the resulting total emitted kg/s and closed mass budget.
