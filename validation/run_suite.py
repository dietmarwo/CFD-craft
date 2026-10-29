#!/usr/bin/env python3
"""Analytic verification with actual CLI runs, frozen numerical targets."""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import numpy as np
from scipy.special import ndtr
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tutorials"))
from common import run_case,accepted,write_report,require

def gaussian_reference(c,t):
    init=c["initial_conditions"][0];u=c["flow"]["velocity_m_s"]
    diffusivity=c["constituents"][0]["diffusivity_m2_s"]
    dimensions=[]
    for a,(length,n) in enumerate(zip(c["domain"]["size_m"],c["grid"]["cells"])):
        h=length/n;x=np.arange(n)*h
        sigma=math.sqrt(init["sigma_m"][a]**2+2*diffusivity*t)
        center=init["center_m"][a]+u[a]*t
        v=np.zeros(n)
        for im in range(-8,9):
            v+=(ndtr((x+h-center+im*length)/sigma)-ndtr((x-center+im*length)/sigma))/h
        dimensions.append(v)
    a,b,d=dimensions
    ref=d[:,None,None]*b[None,:,None]*a[None,None,:]
    return ref*init["total_mass_kg"]

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--binary",type=Path,default=ROOT/"target/release/cfd-craft")
    ap.add_argument("--output",type=Path,required=True);ap.add_argument("--preset",choices=["smoke","study"],default="smoke")
    args=ap.parse_args();args.output.mkdir()
    records=[];report=dict(schema_version="cfd-craft.verification-suite/0.1",passed=False,runs=records)
    try:
        base=json.loads((ROOT/"cases/verification/periodic-tracer.json").read_text())
        errors=[]
        sizes=[24,36,48] if args.preset=="smoke" else [48,72,96]
        for nx in sizes:
            c=copy.deepcopy(base);c["name"]=f"gaussian-{nx}";c["grid"]["cells"]=[nx,nx//2,nx//2]
            c["output"]["max_total_mib"]=256;c["run"]["wall_time_limit_s"]=180.
            r=run_case(args.binary,c,args.output/f"gaussian-{nx}");records.append(r);require(accepted(r),"Gaussian case failed")
            s=json.loads((args.output/f"gaussian-{nx}/fields.json").read_text())
            values=np.array(s["concentrations"][0]).reshape(nx//2,nx//2,nx)
            ref=gaussian_reference(c,s["time_s"])
            error=float(np.linalg.norm(values-ref)/np.linalg.norm(ref));errors.append(error)
        require(errors[2]<errors[1]<errors[0],"Gaussian refinement does not reduce error")
        order=math.log(errors[1]/errors[2])/math.log(sizes[2]/sizes[1])
        report["gaussian"]=dict(sizes=sizes,relative_l2_errors=errors,observed_order_last_pair=order,
            scope="MUSCL/SSPRK2 transport on a periodic 3D Gaussian; observed order, not assumed")
        p=json.loads((ROOT/"cases/verification/poiseuille.json").read_text())
        r=run_case(args.binary,p,args.output/"poiseuille");records.append(r);require(accepted(r),"Poiseuille")
        s=json.loads((args.output/"poiseuille/fields.json").read_text())
        nx,ny,nz=p["grid"]["cells"];nf=nx if p["boundaries"]["x"]=="periodic" else nx+1
        u=np.array(s["velocity"][:nf*ny*nz]).reshape(nz,ny,nf).mean(axis=(1,2))
        z=(np.arange(nz)+.5)/nz;exact=5*z*(1-z);err=float(max(abs(u-exact)))
        require(err<.006,"Poiseuille profile accuracy")
        report["poiseuille"]=dict(maximum_absolute_error_m_s=err,cells=nz)
        # This is a separate physical-consistency gate, not implied by transient completion.
        p=json.loads((ROOT/"cases/verification/empty-abl.json").read_text())
        r=run_case(args.binary,p,args.output/"empty-abl");records.append(r);require(accepted(r),"ABL numerical run")
        s=json.loads((args.output/"empty-abl/fields.json").read_text());nx,ny,nz=p["grid"]["cells"]
        z=(np.arange(nz)+.5)*p["domain"]["size_m"][2]/nz;f=p["flow"]
        us=.4*f["speed_m_s"]/math.log((f["reference_height_m"]+f["roughness_m"])/f["roughness_m"])
        # Fixed region H..5H, excluding wall-function and upper-boundary layers.
        selected=(z>=f["reference_height_m"])&(z<=5*f["reference_height_m"])
        U=us/.4*np.log((z+f["roughness_m"])/f["roughness_m"])
        K=np.full_like(z,us**2/.3);E=us**3/(.4*(z+f["roughness_m"]))
        uu=np.array(s["velocity"][:(nx+1)*ny*nz]).reshape(nz,ny,nx+1)[:,:,-2].mean(axis=1)
        kk=np.array(s["k"]).reshape(nz,ny,nx)[:,:,-2].mean(axis=1)
        ee=np.array(s["epsilon"]).reshape(nz,ny,nx)[:,:,-2].mean(axis=1)
        drifts=[float(max(abs(v[selected]/ref[selected]-1))) for v,ref in [(uu,U),(kk,K),(ee,E)]]
        report["empty_abl"]=dict(region_z_m=[f["reference_height_m"],5*f["reference_height_m"]],
            fetch_x_m=(nx-1.5)*p["domain"]["size_m"][0]/nx,
            max_relative_drift_U_k_epsilon=drifts,thresholds=[.02,.05,.05],passed=all(a<=b for a,b in zip(drifts,[.02,.05,.05])))
        require(report["empty_abl"]["passed"],"Empty ABL homogeneity gate failed")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(1,3,figsize=(10,4))
        for ax,v,ref,label in zip(axes,[uu,kk,ee],[U,K,E],["U (m/s)","k (m2/s2)","epsilon (m2/s3)"]):
            ax.plot(ref,z,label="Inlet reference");ax.plot(v,z,"--",label="Near outlet");ax.set(xlabel=label,ylabel="Height (m)")
        axes[0].legend(fontsize=8);fig.tight_layout();fig.savefig(args.output/"abl-profiles.png",dpi=150);plt.close(fig)
        report["passed"]=True
    except Exception as exc:report["error"]=str(exc)
    finally:write_report(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k!="runs"},indent=2))
    return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
