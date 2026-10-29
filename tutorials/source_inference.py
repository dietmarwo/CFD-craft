#!/usr/bin/env python3
"""Three-source inverse tutorial, held-out sensors and model mismatch."""
import argparse
import copy
import itertools
import json
from pathlib import Path
import numpy as np
from scipy.optimize import nnls
from common import ROOT,run_case,accepted,write_report,require

def values(r):
    return np.array(list(r["summary"]["constituents"][0]["receptors_kg_m3"].values()))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--binary",default=ROOT/"target/release/cfd-craft",type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--preset",choices=["smoke","study"],default="smoke")
    args=p.parse_args();args.output.mkdir()
    case=json.loads((ROOT/"cases/verification/source-response.json").read_text())
    require(case["numerics"]["transport"]=="linear_upwind","exact response matrix requires the linear transport mode")
    records=[];report=dict(schema_version="cfd-craft.inference/0.1",passed=False,runs=records)
    try:
        columns=[]
        for i,source in enumerate(case["sources"]):
            c=copy.deepcopy(case);c["name"]=f"unit-source-{i}";c["sources"]=[source]
            r=run_case(args.binary,c,args.output/f"source-{i}");records.append(r)
            require(accepted(r),f"unit-source {i} did not converge/pass")
            columns.append(values(r))
        G=np.array(columns).T
        rates=np.array([.7,1.3,.9])
        combined=copy.deepcopy(case);combined["name"]="combined-truth"
        for s,q in zip(combined["sources"],rates):s["rate_kg_s_m3"]*=float(q)
        r=run_case(args.binary,combined,args.output/"combined");records.append(r);require(accepted(r),"combined solve")
        y=values(r)
        defect=float(np.linalg.norm(G@rates-y)/np.linalg.norm(y))
        require(defect<1e-4,"source superposition beyond declared steady-solve error")
        train=[0,1,2,3];test=[4,5]
        fit,residual=nnls(G[train],y[train])
        require(np.linalg.norm(fit-rates)/np.linalg.norm(rates)<1e-3,"noiseless rate recovery")
        holdout=float(np.linalg.norm((G@fit-y)[test])/np.linalg.norm(y[test]))
        require(holdout<1e-3,"held-out prediction")
        singular=np.linalg.svd(G[train],compute_uv=False)
        rng=np.random.default_rng(20261029)
        noisy_same_model=y*(1+rng.uniform(-.02,.02,size=len(y)))
        noisy_fit,_=nnls(G[train],noisy_same_model[train])
        ambiguous=G.copy();ambiguous[:,2]=ambiguous[:,1]
        best=[]
        for rows in itertools.combinations(range(6),3):
            score=float(np.linalg.svd(G[list(rows)],compute_uv=False)[-1])
            best.append((score,rows))
        report.update(G=G.tolist(),true_rate_multipliers=rates.tolist(),fitted_rate_multipliers=fit.tolist(),
            relative_superposition_defect=defect,heldout_relative_error=holdout,
            singular_values=singular.tolist(),condition_number=float(singular[0]/singular[-1]),
            ambiguous_rank=int(np.linalg.matrix_rank(ambiguous)),
            best_sensor_indices=list(max(best)[1]),scope="synthetic known-location rates, no posterior claim")
        report["bounded_noise"]=dict(seed=20261029,relative_bound=.02,
            fitted_rate_multipliers=noisy_fit.tolist(),
            relative_rate_error=float(np.linalg.norm(noisy_fit-rates)/np.linalg.norm(rates)),
            heldout_error=float(np.linalg.norm((G@noisy_fit-noisy_same_model)[test])/np.linalg.norm(noisy_same_model[test])))
        require(report["ambiguous_rank"]==2,"ambiguous fixture rank")
        # Different-inflow observations always demonstrate model mismatch.
        mismatch=copy.deepcopy(combined);mismatch["name"]="heldout-inflow";mismatch["flow"]["velocity_m_s"][0]*=1.15
        if args.preset=="study":mismatch["grid"]["cells"]=[48,18,18]
        r=run_case(args.binary,mismatch,args.output/"mismatch");records.append(r);require(accepted(r),"mismatch solve")
        noisy=values(r);altered_fit,_=nnls(G[train],noisy[train])
        report["model_mismatch"]=dict(fitted_rate_multipliers=altered_fit.tolist(),
            true_rate_multipliers=rates.tolist(),
            relative_rate_error=float(np.linalg.norm(altered_fit-rates)/np.linalg.norm(rates)),
            heldout_error=float(np.linalg.norm((G@altered_fit-noisy)[test])/np.linalg.norm(noisy[test])))
        np.savetxt(args.output/"response-matrix.csv",G,delimiter=",",header="S0,S1,S2",comments="")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(6,3))
        ax.plot(rates,"o-",label="True");ax.plot(fit,"x--",label="Same-model fit")
        ax.plot(altered_fit,"s:",label="Changed-inflow fit")
        ax.set(xlabel="Source index",ylabel="Emission multiplier");ax.legend();fig.tight_layout()
        fig.savefig(args.output/"source-inference.png",dpi=150);plt.close(fig)
        report["passed"]=True
    except Exception as exc:
        report["error"]=str(exc)
    finally:write_report(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k!="runs"},indent=2))
    return 0 if report["passed"] else 1

if __name__=="__main__":raise SystemExit(main())
