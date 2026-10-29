#!/usr/bin/env python3
"""2D lid cavity (periodic invariant span): numerical benchmark, not urban validation.

Ghia Re=100 centerline U values are tabulated in Sandia's Fuego Verification
Manual, table 22.1-1, citing Ghia et al. (1982):
https://www.sandia.gov/app/uploads/sites/315/2025/11/Fuego_Verification_5_18.pdf
We map the benchmark's vertical y coordinate to local z.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tutorials"))
from common import run_case,accepted,require,write_report

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--binary",type=Path,default=ROOT/"target/release/cfd-craft")
    ap.add_argument("--output",type=Path,required=True);args=ap.parse_args();args.output.mkdir()
    report=dict(schema_version="cfd-craft.cavity/0.1",passed=False,runs=[])
    try:
        c=json.loads((ROOT/"cases/verification/lid-cavity.json").read_text())
        r=run_case(args.binary,c,args.output/"cavity");report["runs"].append(r);require(accepted(r),"cavity numerical checks")
        s=json.loads((args.output/"cavity/fields.json").read_text());nx,ny,nz=c["grid"]["cells"]
        U=np.array(s["velocity"][:(nx+1)*ny*nz]).reshape(nz,ny,nx+1)[:,:,nx//2].mean(axis=1)
        stations=np.loadtxt(ROOT/"validation/ghia-re100-u.csv",delimiter=",",skiprows=1)
        z=np.r_[0,(np.arange(nz)+.5)/nz,1];u=np.r_[0,U,1]
        predicted=np.interp(stations[:,0],z,u)
        error=float(max(abs(predicted-stations[:,1])))
        report.update(maximum_centerline_absolute_error=error,target_max=.06,
            grid=c["grid"]["cells"],physical_time_s=s["time_s"],
            reference="Ghia Re=100, as tabulated in Sandia Fuego Verification Manual 5.18 table 22.1-1")
        require(error<=.06,"cavity profile differs from benchmark beyond fixed coarse-grid tolerance")
        report["passed"]=True
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(4,4));ax.plot(u,z,label="CFD-craft");ax.plot(stations[:,1],stations[:,0],"x",label="Ghia Re=100")
        ax.set(xlabel="U / lid speed",ylabel="z / H");ax.legend();fig.tight_layout();fig.savefig(args.output/"cavity.png",dpi=150);plt.close(fig)
    except Exception as e:report["error"]=str(e)
    finally:write_report(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k!="runs"},indent=2));return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
