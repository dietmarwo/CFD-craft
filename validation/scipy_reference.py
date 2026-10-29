#!/usr/bin/env python3
"""Independent steady uniform-flow transport matrix, assembled with SciPy."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import scipy
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tutorials"))
from common import run_case,accepted,require,write_report

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--binary",type=Path,default=ROOT/"target/release/cfd-craft")
    ap.add_argument("--output",type=Path,required=True);args=ap.parse_args();args.output.mkdir()
    report=dict(schema_version="cfd-craft.scipy-reference/0.1",passed=False,runs=[])
    try:
        c=json.loads((ROOT/"cases/verification/source-response.json").read_text())
        require(c["flow"]["kind"]=="prescribed_uniform" and c["numerics"]["transport"]=="linear_upwind","reference scope")
        r=run_case(args.binary,c,args.output/"native");report["runs"].append(r);require(accepted(r),"native transport solve")
        n=c["grid"]["cells"];h=np.array(c["domain"]["size_m"])/n;count=int(np.prod(n))
        A=lil_matrix((count,count));b=np.zeros(count);u=c["flow"]["velocity_m_s"];D=c["constituents"][0]["diffusivity_m2_s"]
        def ix(q):return (q[2]*n[1]+q[1])*n[0]+q[0]
        for k in range(n[2]):
            for j in range(n[1]):
                for i in range(n[0]):
                    q=[i,j,k];row=ix(q);center=(np.array(q)+.5)*h
                    for a in range(3):
                        periodic=c["boundaries"]["xyz"[a]]=="periodic"
                        # Upwind advection: derivative from the upstream neighbor.
                        if u[a]!=0:
                            side=-1 if u[a]>0 else 1;neighbor=q.copy();neighbor[a]+=side
                            A[row,row]+=abs(u[a])/h[a]
                            if periodic:neighbor[a]%=n[a]
                            if 0<=neighbor[a]<n[a]:A[row,ix(neighbor)]-=abs(u[a])/h[a]
                        for side in [-1,1]:
                            neighbor=q.copy();neighbor[a]+=side
                            if periodic:neighbor[a]%=n[a]
                            if 0<=neighbor[a]<n[a]:
                                A[row,row]+=D/h[a]**2;A[row,ix(neighbor)]-=D/h[a]**2
                            elif u[a]*side<0:
                                # Zero concentration, half-cell Dirichlet inlet.
                                A[row,row]+=2*D/h[a]**2
                    for source in c["sources"]:
                        require(source["kind"]=="volume","reference volume sources only")
                        overlap=np.maximum(0.,np.minimum(source["max_m"],center+.5*h)-np.maximum(source["min_m"],center-.5*h))
                        b[row]+=source["rate_kg_s_m3"]*np.prod(overlap)/np.prod(h)
        ref=spsolve(A.tocsr(),b)
        s=json.loads((args.output/"native/fields.json").read_text());native=np.array(s["concentrations"][0])
        relative=float(np.linalg.norm(native-ref)/np.linalg.norm(ref))
        residual=float(np.linalg.norm(A@native-b)/np.linalg.norm(b))
        report.update(scipy_version=scipy.__version__,relative_field_difference=relative,
            relative_assembled_residual=residual,target_field_difference=5e-5,
            scope="independent code/discrete transport check; not empirical RANS validation")
        require(relative<5e-5,"native steady field differs from direct reference")
        report["passed"]=True
    except Exception as e:report["error"]=str(e)
    finally:write_report(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k!="runs"},indent=2));return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
