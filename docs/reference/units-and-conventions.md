# Units and conventions

Every quantity has one unit, carried by its field name (`velocity_m_s`).
Nothing is converted silently. Time is in seconds.

## Setup

Commands run from the root of a checkout with `target/release` on `PATH`.

## Units

| Quantity | Unit or convention |
|---|---|
| Position and domain size | meters; x east, y north, z up (local coordinates) |
| Velocity | m/s |
| Pressure | kinematic pressure, m2/s2; with RANS the isotropic part 2k/3 is absorbed |
| k and epsilon | m2/s2 and m2/s3 |
| Concentration | kg/m3; multiply by 1e9 for micrograms/m3 |
| Source rate | kg/s (point), kg/(s m) (line), kg/(s m3) (volume) |
| Diffusivity and viscosity | m2/s |
| Particle diameter and density | meters (`diameter_m`: 1e-6 is one micrometer, allowed 1e-8 to 1e-4) and kg/m3 (`density_kg_m3`, the density of the particle material) |
| Settling and deposition velocity | m/s, positive downward or onto the surface (0 to 10) |
| Deposited mass and deposition rate | kg and kg/s per surface class: `ground`, `roof`, `vegetation` |
| Leaf area density and drag coefficient | m2 of leaf area per m3 of canopy (`leaf_area_density_m2_m3`, 0 to 100); dimensionless (0 to 10) |
| Roughness length | meters (`flow.roughness_m` for the ground, `building_roughness_m` for building walls) |
| Path receptor | corners as east and north in meters, one `height_m` above the ground; `distance_m` is the length along the route from its first corner |
| Street emission rate | kg/(s m): `rate_kg_s_m` of a line source; the street CSV requires `units` to be exactly `kg/s/m` |

A point (a point source, an end of a line source, a point receptor) is inside
the domain when 0 <= coordinate < size on every axis, so a point on an upper
domain face is outside (`CFD-E017`, `CFD-E027`). A box may reach the faces.

`describe` states the coordinates and the pressure unit itself:

```bash
cfd-craft describe | python -c "import json,sys; d=json.load(sys.stdin); print(d['coordinates']); print(d['pressure_units'])"
```

```text
local east, north, up; meteorological wind direction from
kinematic m2/s2; RANS isotropic 2k/3 absorbed
```

## Wind direction

Wind direction is the meteorological direction the wind comes from, in degrees
clockwise from north (`flow.direction_deg_from` of a `neutral_rans` case). A wind
from 270 degrees travels in positive x; from 225 degrees, toward positive x and
y. Native gas inflows carry a zero concentration increment; an ambient
background is a separate physical interpretation, not a hidden source.

## Particles

A particle bin has one diameter and one density. Its settling speed is the
Stokes speed with the Cunningham slip correction in air at 293.15 K and
101325 Pa (density 1.204 kg/m3, viscosity 1.81e-5 Pa s, mean free path
6.6e-8 m, gravity 9.80665 m/s2), unless the case gives
`settling_velocity_m_s`. The result reports the speed used
(`settling_velocity_m_s`) and the aerodynamic diameter
(`aerodynamic_diameter_m`): the diameter of a sphere of density 1000 kg/m3
with the same settling speed. `particulate_matter` has the entries `PM2.5` and
`PM10`: sums over the bins whose aerodynamic diameter is at most 2.5e-6 m or
1e-5 m. A deposition velocity in the case is added to the settling speed on
ground and roofs; it does not include settling.

## Maps and rotated frames

The map converter works in a projected coordinate system in meters and
rotates the buildings clockwise by `rotation_deg` about the center of the
crop. The case is in the rotated model frame: model direction = map direction
+ `rotation_deg` (modulo 360), and `map-provenance.json` keeps both. A path
receptor and a line source are given in the model frame; the street converter
applies the recorded rotation and translation for you.

## Sensor rides

A virtual ride uses seconds for time, the reading interval and the response
time, m/s for the riding speed and kg/m3 for the field and the sensor
reading. Response-matrix columns are in kg/m3 per unit multiplier of a source
group; the reference rate of a group is in kg/s.

## Array ordering

Concentration, pressure, k and epsilon are cell values; velocity components
live on faces. For `cells = [nx, ny, nz]`:

- Cells are x-fastest: cell `(i, j, k)` has index `(k*ny + j)*nx + i`.
- Face arrays are concatenated by component (x, y, z), each x-fastest, with one
  additional face along its own axis when that axis is not periodic (periodic
  arrays wrap and do not repeat an end face).

```python
nx, ny, i, j, k = 4, 3, 1, 2, 1
print((k * ny + j) * nx + i)
```

```text
21
```

Prefer the VTK exporter (see [scripts](scripts.md)) to hand-written reshaping.
