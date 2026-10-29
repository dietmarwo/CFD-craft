#!/usr/bin/env python3
"""Run a CFD command and actual scalar application profiles on a foreground node."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"validation"))
from check_fields import require

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--runner",type=Path,required=True)
    ap.add_argument("--binary",type=Path,default=ROOT/"target/release/cfd-craft")
    ap.add_argument("--worker",type=Path,default=ROOT/"integrations/fcmaes-cfd-worker/target/release/fcmaes-cfd-worker")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output=args.output.resolve();args.output.mkdir()
    runner=args.runner.resolve();node=args.output/"node"
    actions=[];report=dict(schema_version="cfd-craft.job-integration/0.1",passed=False,actions=actions)
    def call(*cmd):
        p=subprocess.run([str(runner),"--root",str(node),*map(str,cmd)],capture_output=True,text=True,timeout=240)
        record=dict(command=list(map(str,cmd)),returncode=p.returncode)
        actions.append(record)
        (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        require(p.returncode==0,f"runner {cmd}: {p.stderr} {p.stdout}")
        try:value=json.loads(p.stdout)
        except json.JSONDecodeError:value=p.stdout
        record["result"]=value;return value
    try:
        call("node","init","--capacity","4","--allow-commands")
        case=args.output/"command-case.json"
        c=json.loads((ROOT/"cases/verification/periodic-tracer.json").read_text())
        c["grid"]["cells"]=[12,6,6];c["run"]["threads"]=1
        case.write_text(json.dumps(c))
        launcher=args.output/"launch.py";launcher.write_bytes((ROOT/"integrations/launch_command.py").read_bytes())
        solver=args.output/"solver-bin";shutil.copyfile(args.binary.resolve(),solver)
        spec=dict(schema_version="execution.command/0.1",request_key="cfd-command-v1",
            argv=[sys.executable,"launch.py","./solver"],env={},
            resources=dict(cpu_slots=1),limits=dict(wall_seconds=60,grace_seconds=2),replay="never",
            inputs=[dict(path="case.json",file=case.name,bytes=case.stat().st_size,sha256=hashlib.sha256(case.read_bytes()).hexdigest(),executable=False),
                dict(path="launch.py",file=launcher.name,bytes=launcher.stat().st_size,sha256=hashlib.sha256(launcher.read_bytes()).hexdigest(),executable=False),
                dict(path="solver",file=solver.name,bytes=solver.stat().st_size,sha256=hashlib.sha256(solver.read_bytes()).hexdigest(),executable=True)],
            outputs=[dict(name="summary",path="summary.json",required=True,max_bytes=1048576)])
        p=args.output/"command.json";p.write_text(json.dumps(spec,indent=2))
        command_result=call("run","--spec",p)
        require(command_result.get("state")=="completed","CFD command execution did not complete")
        report["command_result"]=command_result
        call("workers","add","--id","cfd","--executable",args.worker.resolve())
        described=json.loads(subprocess.check_output([str(args.worker.resolve()),"describe"],text=True))
        examples={x["profile"]:x for x in described["examples"]}
        for profile in ["fcmaes.evaluate/1","fcmaes.retry/1","fcmaes.surrogate/1"]:
            example=copy.deepcopy(examples[profile]);inputs=[]
            for item in example["inputs"]:
                data=item.get("content_text")
                if data is None:data=json.dumps(item["content"])
                q=args.output/item["file"];q.write_text(data)
                inputs.append(dict(name=item["name"],file=item["file"],sha256=hashlib.sha256(q.read_bytes()).hexdigest()))
            payload=example["payload"]
            if profile=="fcmaes.evaluate/1":
                payload["points"]=[[1.,1.],[.9,.9]]
            elif profile=="fcmaes.retry/1":
                payload.pop("guess",None)
                payload.update(retries=1,evaluations_per_retry=24,
                    evaluation_limit_mode="hard",optimizer=dict(kind="biteopt",parameters={}))
            else:
                payload.update(evaluations=24,runs=1,concurrent=2,evaluation_threads=1,recheck_best=True)
            job=dict(schema_version="optimization.job/0.1",request_key=profile.replace("/","-").replace(".","-")+"-cfd-v1",
                worker="cfd",payload_schema=profile,resources=dict(cpu_slots=2,outer_workers=1,inner_threads=2),
                limits=dict(wall_time_seconds=180.,grace_seconds=2.),inputs=inputs,payload=payload)
            if profile!="fcmaes.surrogate/1":job["resources"]=dict(cpu_slots=1,outer_workers=1,inner_threads=1)
            jp=args.output/(profile.split("/")[0]+".json");jp.write_text(json.dumps(job,indent=2))
            result=call("run","--spec",jp)
            require(result.get("state")=="completed","optimizer job did not complete")
            manifest=call("result",result["directory"])
            report[profile]=dict(execution=result,result=manifest)
            require(result.get("completed_tasks")==result.get("requested_tasks"),"incomplete optimizer tasks")
            require(result.get("known_work_lower_bound",{}).get("failed_evaluations",0)==0,"CFD evaluation failure")
        report["passed"]=True
        report["interpretation"]="runner execution and optimizer outcomes; CFD numerical checks are inside each fallible simulation; no CFD claim added to optimization.result"
    except Exception as exc:report["error"]=str(exc)
    finally:(args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2));return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
