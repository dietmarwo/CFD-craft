#!/usr/bin/env python3
"""Generate canonical release fixtures. No solver results are fabricated here."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def base(name="transport", cells=(24, 12, 12)):
    return dict(schema_version="cfd-craft.case/0.1", name=name,
        domain=dict(size_m=[12., 6., 6.]), grid=dict(cells=list(cells)),
        boundaries=dict(x="periodic", y="periodic", z="periodic"),
        flow=dict(kind="prescribed_uniform", velocity_m_s=[0.5, 0., 0.]),
        geometry=[], constituents=[dict(id="tracer", diffusivity_m2_s=0.05)],
        initial_conditions=[dict(kind="periodic_gaussian", constituent="tracer",
            center_m=[3.,3.,3.], sigma_m=[0.7,0.7,0.7], total_mass_kg=1e-6)],
        sources=[], receptors=[dict(kind="volume_average", id="R1",
            min_m=[4.5,2.5,2.5], max_m=[5.5,3.5,3.5])],
        numerics=dict(transport="muscl", max_time_step_s=0.1, advective_cfl_max=0.4,
            pressure_relative_tolerance=1e-10, pressure_max_iterations=1200,
            steady_residual_tolerance=1e-5, steady_monitor_tolerance=1e-3, monitor_window=30),
        run=dict(mode="transient", end_time_s=2., max_steps=20000,wall_time_limit_s=120.,
            threads=2,memory_limit_mib=1024),
        output=dict(fields=True, checkpoint=True, max_total_mib=64))

def canyon(aspect=1., direction=270., cells=(36,40,16), name=None):
    c=base(name or f"canyon-wh{aspect:g}-wind{direction:g}", cells)
    c["domain"]["size_m"]=[18.,16.,6.]
    c["boundaries"]=dict(x="open",y="open",z="ground_open_top")
    c["flow"]=dict(kind="neutral_rans",speed_m_s=2.,reference_height_m=1.,
        roughness_m=0.01,direction_deg_from=direction,viscosity_m2_s=1.5e-5,
        turbulent_schmidt=0.7)
    c["geometry"]=[dict(id="west",min_m=[5.,3.,0.],max_m=[6.,13.,1.]),
        dict(id="east",min_m=[6.+aspect,3.,0.],max_m=[7.+aspect,13.,1.])]
    c["initial_conditions"]=[]
    c["sources"]=[dict(kind="line",id="traffic",constituent="tracer",
        from_m=[6.+aspect/2,3.,0.15],to_m=[6.+aspect/2,13.,0.15],
        rate_kg_s_m=1e-8)]
    # Sample inside the canyon, with support away from staircase walls.
    c["receptors"]=[dict(kind="point",id=f"sensor{n}",
        point_m=[6.+aspect/2,y,z]) for n,(y,z) in enumerate([(5.,0.4),(8.,0.4),(11.,0.4),(8.,0.8)])]
    c["run"].update(mode="steady",end_time_s=100.,max_steps=6000,wall_time_limit_s=240.,threads=4)
    c["numerics"].update(max_time_step_s=0.1,transport="linear_upwind",monitor_window=40)
    return c

def save(path,c):
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(c,indent=2)+"\n")
def main():
    save("cases/verification/periodic-tracer.json",base())
    p=base("pressure", (8,8,8));p["constituents"]=[];p["initial_conditions"]=[];p["receptors"]=[]
    save("cases/verification/pressure.json",p)
    p=base("poiseuille",(4,4,16));p["domain"]["size_m"]=[1.,1.,1.]
    p["flow"]=dict(kind="laminar",initial_velocity_m_s=[0.,0.,0.],viscosity_m2_s=0.1,
        acceleration_m_s2=[1.,0.,0.])
    p["boundaries"]["z"]="wall";p["constituents"]=[];p["initial_conditions"]=[];p["receptors"]=[]
    p["run"].update(end_time_s=15.,wall_time_limit_s=120.)
    save("cases/verification/poiseuille.json",p)
    q=copy.deepcopy(p);q["name"]="couette";q["flow"]["acceleration_m_s2"]=[0.,0.,0.]
    q["moving_walls"]=[dict(axis=2,upper=True,velocity_m_s=[1.,0.,0.])]
    save("cases/verification/couette.json",q)
    q=copy.deepcopy(q);q["name"]="lid-cavity-re100";q["grid"]["cells"]=[24,2,24]
    q["boundaries"]["x"]="wall";q["flow"]["viscosity_m2_s"]=0.01
    q["run"].update(end_time_s=30.,wall_time_limit_s=180.)
    save("cases/verification/lid-cavity.json",q)
    p=canyon(name="empty-abl",cells=(16,4,48));p["geometry"]=[];p["sources"]=[]
    p["constituents"]=[];p["receptors"]=[];p["run"].update(mode="transient",end_time_s=8.,max_steps=10000)
    save("cases/verification/empty-abl.json",p)
    for aspect,wind in [(1,270),(2,270),(1,225)]:
        save(f"cases/canyon/wh{aspect}-wind{wind}.json",canyon(aspect,wind))
    p=base("source-response",(32,12,12));p["domain"]["size_m"]=[16.,6.,6.]
    p["boundaries"]["x"]="open";p["initial_conditions"]=[]
    p["flow"]["velocity_m_s"]=[1.,0.,0.]
    p["constituents"][0]["diffusivity_m2_s"]=0.08
    p["sources"]=[dict(kind="volume",id=f"S{i}",constituent="tracer",
        min_m=[2.,y-0.4,2.6],max_m=[3.,y+0.4,3.4],rate_kg_s_m3=1e-7)
        for i,y in enumerate([1.5,3.,4.5])]
    p["receptors"]=[dict(kind="volume_average",id=f"R{i}",min_m=[x-0.25,y-0.25,2.75],
        max_m=[x+0.25,y+0.25,3.25]) for i,(x,y) in enumerate(
        [(7.,1.5),(7.,3.),(7.,4.5),(12.,1.5),(12.,3.),(12.,4.5)])]
    p["run"].update(mode="steady",max_steps=6000,wall_time_limit_s=120.)
    p["numerics"]["transport"]="linear_upwind"
    save("cases/verification/source-response.json",p)

if __name__=="__main__":main()
