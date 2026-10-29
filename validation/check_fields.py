#!/usr/bin/env python3
"""Independent archived-field checks. Essential checks survive python -O."""
import hashlib
import json
from pathlib import Path
import sys
import math

def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def check(path):
    path=Path(path)
    marker=json.loads((path/"complete.json").read_text())
    require(sha(path/"manifest.json")==marker["manifest_sha256"],"manifest hash")
    manifest=json.loads((path/"manifest.json").read_text())
    for name,digest in manifest["files"].items():
        require(Path(name).name==name,"artifact path")
        require(not (path/name).is_symlink(),"symlink artifact")
        require(sha(path/name)==digest,f"artifact hash: {name}")
    c=json.loads((path/"case.json").read_text())
    summary=json.loads((path/"summary.json").read_text())
    require((path/"fields.json").is_file(),"full fields unavailable; cannot independently check")
    s=json.loads((path/"fields.json").read_text())
    nx,ny,nz=c["grid"]["cells"];n=nx*ny*nz
    dx=[L/N for L,N in zip(c["domain"]["size_m"],[nx,ny,nz])]
    volume=math.prod(dx)
    index=lambda i,j,k:(k*ny+j)*nx+i
    fluid=[True]*n
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                p=[(i+.5)*dx[0],(j+.5)*dx[1],(k+.5)*dx[2]]
                fluid[index(i,j,k)]=not any(all(lo<=x<hi for lo,x,hi in zip(b["min_m"],p,b["max_m"])) for b in c["geometry"])
    components=[];offset=0
    for a in range(3):
        dims=[nx,ny,nz];periodic=c["boundaries"]["xyz"[a]]=="periodic"
        if not periodic:dims[a]+=1
        count=math.prod(dims);values=s["velocity"][offset:offset+count];offset+=count
        components.append((dims,values))
    require(offset==len(s["velocity"]),"face count")
    max_div=0.
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                if not fluid[index(i,j,k)]:continue
                div=0.
                for a,(dims,v) in enumerate(components):
                    p=[i,j,k];lo=(p[2]*dims[1]+p[1])*dims[0]+p[0]
                    p[a]+=1
                    if c["boundaries"]["xyz"[a]]=="periodic":p[a]%=[nx,ny,nz][a]
                    hi=(p[2]*dims[1]+p[1])*dims[0]+p[0]
                    div+=(v[hi]-v[lo])/dx[a]
                max_div=max(max_div,abs(div))
    speed=summary["velocity_max_m_s"]
    require(max_div<=1e-7*max(1.,speed)/min(dx),"independent local continuity")
    scalar_results=[]
    for sp,values,budget,record in zip(c["constituents"],s["concentrations"],s["budgets"],summary["constituents"]):
        require(len(values)==n and all(math.isfinite(v) for v in values),"scalar dimensions/finiteness")
        mass=math.fsum(values)*volume
        scale=max(budget["initial_kg"]+budget["emitted_kg"]+budget["inflow_kg"]+budget["outflow_kg"],1e-30)
        defect=mass-budget["initial_kg"]-budget["emitted_kg"]-budget["inflow_kg"]+budget["outflow_kg"]
        require(abs(mass-record["mass_kg"])<1e-11*scale,"reported mass mismatch")
        require(abs(defect)<1e-9*scale,"independent mass accounting")
        require(min(values)>=-1e-10*max(max(values),1e-30),"negative concentration")
        rate=0.
        for source in c["sources"]:
            if source["constituent"]!=sp["id"]:continue
            if source["kind"]=="point":rate+=source["rate_kg_s"]
            elif source["kind"]=="line":
                rate+=source["rate_kg_s_m"]*math.dist(source["from_m"],source["to_m"])
            else:rate+=source["rate_kg_s_m3"]*math.prod(b-a for a,b in zip(source["min_m"],source["max_m"]))
        require(abs(budget["emitted_kg"]-rate*s["time_s"])<1e-9*scale,"emission normalization/time accounting")
        # Reconstruct current open-boundary scalar removal from archived face velocities.
        incoming=0.;outgoing=0.
        for a,(dims,face_values) in enumerate(components):
            if c["boundaries"]["xyz"[a]]!="open":continue
            for k in range(nz):
                for j in range(ny):
                    for i in range(nx):
                        q=[i,j,k]
                        for side in [-1,1]:
                            if q[a]!=(0 if side<0 else [nx,ny,nz][a]-1):continue
                            cell=index(i,j,k)
                            if not fluid[cell]:continue
                            face=q.copy()
                            if side>0:face[a]+=1
                            fi=(face[2]*dims[1]+face[1])*dims[0]+face[0]
                            normal_u=side*face_values[fi]
                            f=c["flow"]
                            if f["kind"]=="neutral_rans":
                                angle=math.radians(f["direction_deg_from"])
                                nominal=[-math.sin(angle),-math.cos(angle),0.][a]*side
                                nu_t=.09*s["k"][cell]**2/s["epsilon"][cell] if s["epsilon"][cell]>0 else 0.
                                D=sp["diffusivity_m2_s"]+nu_t/f["turbulent_schmidt"]
                            else:
                                nominal=side*f.get("velocity_m_s",f.get("initial_velocity_m_s"))[a]
                                D=sp["diffusivity_m2_s"]
                            flux=max(normal_u,0.)*values[cell]*volume/dx[a]
                            if nominal< -1e-12:flux+=D*values[cell]/(.5*dx[a])*volume/dx[a]
                            outgoing+=max(flux,0.);incoming+=max(-flux,0.)
        if "source_rate_kg_s" in record:
            flux_scale=max(rate+outgoing+incoming,1e-30)
            require(abs(record["source_rate_kg_s"]-rate)<1e-9*flux_scale,"current source rate")
            require(abs(record["boundary_outflow_rate_kg_s"]-outgoing)<1e-9*flux_scale,"current scalar outflow")
            require(abs(record["boundary_inflow_rate_kg_s"]-incoming)<1e-9*flux_scale,"current scalar inflow")
        scalar_results.append(dict(id=sp["id"],mass_kg=mass,relative_defect=abs(defect)/scale))
    return dict(schema_version="cfd-craft.independent-check/0.1",passed=True,
        max_divergence_s_inv=max_div,scalars=scalar_results,
        scope="archived mass, recorded cumulative budget, emission rate/time, current local continuity; not independent turbulent-model validation")

if __name__=="__main__":
    try:print(json.dumps(check(sys.argv[1]),indent=2))
    except (ValueError,KeyError,OSError,IndexError) as e:
        print(json.dumps(dict(passed=False,error=str(e))));sys.exit(1)
