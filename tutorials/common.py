"""Canonical execution helpers; preserve a report even when a case fails."""
import json
import subprocess
import time
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"validation"))
from check_fields import check,require

def run_case(binary,case,destination,restart=None):
    destination=Path(destination)
    p=destination.with_suffix(".case.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(case,indent=2)+"\n")
    start=time.monotonic()
    command=[str(Path(binary).resolve()),"run",str(p),"--output",str(destination)]
    if restart is not None:command.extend(["--restart",str(restart)])
    completed=subprocess.run(command,
        capture_output=True,text=True,timeout=case["run"]["wall_time_limit_s"]+20)
    destination.with_suffix(".stdout.log").write_text(completed.stdout)
    destination.with_suffix(".stderr.log").write_text(completed.stderr)
    summary_path=destination/"summary.json"
    summary=json.loads(summary_path.read_text()) if summary_path.is_file() else None
    audit=None
    if (destination/"fields.json").exists():
        try:audit=check(destination)
        except (ValueError,OSError,KeyError) as exc:audit=dict(passed=False,error=str(exc))
    return dict(case=case["name"],returncode=completed.returncode,wall_s=time.monotonic()-start,
        summary=summary,independent=audit,path=str(destination.name))

def accepted(record):
    return (record["returncode"]==0 and record["summary"] is not None
        and record["summary"]["assessment"] in ["steady_discrete_solution","transient_interval_completed"]
        and record["independent"] is not None and record["independent"]["passed"])

def write_report(output,report):
    Path(output,"report.json").write_text(json.dumps(report,indent=2)+"\n")
