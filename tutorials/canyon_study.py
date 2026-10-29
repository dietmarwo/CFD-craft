#!/usr/bin/env python3
"""Finite-canyon wind, grid, domain and Schmidt sensitivity; keep failed rows."""
import argparse
import copy
import concurrent.futures
import json
from pathlib import Path
import sys
import numpy as np
from common import ROOT,run_case,accepted,write_report,require

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--binary",type=Path,default=ROOT/"target/release/cfd-craft")
    ap.add_argument("--output",type=Path,required=True);ap.add_argument("--preset",choices=["smoke","sensitivity","study"],default="smoke")
    args=ap.parse_args();args.output.mkdir()
    cases=[]
    for aspect,wind in [(1,270),(2,270),(1,225)]:
        c=json.loads((ROOT/f"cases/canyon/wh{aspect}-wind{wind}.json").read_text())
        c["grid"]["cells"]=[18,16,12];c["run"].update(threads=2,wall_time_limit_s=150.,max_steps=7000)
        cases.append(c)
    if args.preset=="study":
        for dims in [[36,32,24],[54,48,36]]:
            c=copy.deepcopy(cases[0]);c["name"]=f"grid-{'x'.join(map(str,dims))}";c["grid"]["cells"]=dims
            c["output"]["max_total_mib"]=256;c["run"]["wall_time_limit_s"]=300.
            cases.append(c)
    if args.preset in ["study","sensitivity"]:
        for sc in [.5,.9]:
            c=copy.deepcopy(cases[0]);c["name"]=f"schmidt-{sc}";c["flow"]["turbulent_schmidt"]=sc;cases.append(c)
        c=copy.deepcopy(cases[0]);c["name"]="extended-outlet";c["domain"]["size_m"][0]=24.
        c["grid"]["cells"][0]=24;cases.append(c)
    records=[];report=dict(schema_version="cfd-craft.canyon-study/0.1",passed=False,runs=records,
        empirical_validation="blocked_data",physical_claim="none",
        geometry_scope="finite 3D boxes, gas only, intentionally coarse research grids")
    # Two processes * two solver threads; conservative CPU/memory admission.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run_case,args.binary,c,args.output/c["name"]) for c in cases]
        for c,f in zip(cases,futures):
            try:records.append(f.result())
            except Exception as exc:records.append(dict(case=c["name"],error=str(exc),returncode=1,summary=None,independent=None))
            write_report(args.output,report)
    report["numerical_accepted"]=sum(accepted(r) for r in records)
    report["all_numerical_checks_passed"]=all(accepted(r) for r in records)
    if args.preset=="study":
        grid_runs=[records[0],records[3],records[4]]
        if all(accepted(r) for r in grid_runs):
            values=[np.array(list(r["summary"]["constituents"][0]["receptors_kg_m3"].values())) for r in grid_runs]
            delta=float(np.linalg.norm(values[2]-values[1])/max(np.linalg.norm(values[2]),1e-30))
            report["resolution"]=dict(relative_change_two_finest_receptors=delta,
                screening_target=.05,screening_passed=delta<=.05,
                GCI=None,GCI_reason="unequal refinement ratios, near-wall samples, coarse staircase sequence; no asymptotic claim")
    report["passed"]=report["all_numerical_checks_passed"]
    report["release_validation_gate"]="blocked_data; numerical completion alone does not establish physical validity"
    if records[0].get("summary"):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(7,3.5))
        for r in records:
            if r.get("summary") and r["summary"]["constituents"]:
                y=list(r["summary"]["constituents"][0]["receptors_kg_m3"].values())
                ax.plot(range(len(y)),np.array(y)*1e9,"o-",label=r["case"])
        ax.set(xlabel="Receptor",ylabel="Modeled gas concentration (microgram/m3)")
        ax.legend(fontsize=6);fig.tight_layout();fig.savefig(args.output/"canyon-receptors.png",dpi=150);plt.close(fig)
    write_report(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k!="runs"},indent=2))
    return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
