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
