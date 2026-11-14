"""Research loop for single-translation-unit C++ benchmark projects."""
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from statistics import median

from pydantic import Field
from .iteration import stop_reason
from .models import Record
from .science.execution import execute_isolated


class Revision(Record):
    hypothesis: str
    replacement: str = Field(min_length=1,max_length=24000,description="Literal compilable C++ source statements. Include the actual loop and a return statement, not an English description.")


def layout(root, files):
    paths = {}
    for f in files:
        p = PurePosixPath(f.get("archive_path", f["name"]))
        if p.is_absolute() or not p.parts or ".." in p.parts or any(":" in x or "\\" in x for x in p.parts):
            raise ValueError("Invalid project path")
        if str(p) in paths:
            raise ValueError("Duplicate project path")
        paths[str(p)] = root/"inputs"/f["id"]
    return paths


def fingerprint(paths):
    digest = hashlib.sha256()
    for name,path in sorted(paths.items()):
        digest.update(name.encode()+b"\0"+hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def measure(root,payload):
    paths = layout(root,payload["files"])
    # Local native execution is an explicit operator choice for a reviewed project.
    if fingerprint(paths) != os.getenv("LAZYRESEARCH_TRUSTED_NATIVE_SHA256"):
        raise ValueError("Local compilation requires explicit trust for this project fingerprint")
    exe = shutil.which("g++")
    if not exe:
        raise ValueError("Missing g++")
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        work = Path(tmp).resolve()
        for name,path in paths.items():
            dest = work/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,dest)
        (work/payload["editable"]).write_text(payload["source"],encoding="utf8")
        binary = work/"trial.exe"
        result = subprocess.run([exe,"-std=c++17","-O3",str(work/payload["entry"]),"-o",str(binary)],
                                capture_output=True,timeout=25)
        if result.returncode:
            raise ValueError(result.stderr.decode(errors="replace")[-1200:])
        samples=[]
        for _ in range(5):
            proc=subprocess.run([str(binary)],cwd=work,capture_output=True,timeout=8)
            if proc.returncode:
                raise ValueError("Harness failed: "+proc.stderr.decode(errors="replace")[-500:])
            record=json.loads(proc.stdout)
            if record["correct"] is not True or not 0 < record["ns"] < 1e16:
                raise ValueError("Correctness or timing rejected")
            samples.append(record["ns"])
        return {"verdict":"observed","median_ns":median(samples),"samples_ns":samples}


def search(task,material,registry,budget,ask,emit,result,evidence):
    files=material["files"]
    paths=layout(registry.root,files)
    manifest=next(path for name,path in paths.items() if PurePosixPath(name).name=="native-benchmark.json")
    prefix=next(PurePosixPath(name).parent for name,path in paths.items() if path==manifest)
    config=json.loads(manifest.read_text(encoding="utf8"))
    entry,editable=[str(prefix/config[key]) for key in ("entry","editable")]
    if entry not in paths or editable not in paths or entry==editable:
        return result("failed","Invalid native benchmark manifest")
    best=paths[editable].read_text(encoding="utf-8-sig")
    folder=registry.root/"native-result"
    folder.mkdir(exist_ok=True)
    accepted=folder/PurePosixPath(editable).name
    accepted.write_text(best,encoding="utf8")
    feedback=[]
    baseline=best_ns=None
    best_samples=[]
    # For a single function, preserve its declaration/includes mechanically.
    opening = best.find("{")
    closing = best.rfind("}")
    body_only = opening >= 0 and closing > opening and best[:opening].count("(")==1 and not best[closing+1:].strip()
    prefix, suffix = best[:opening+1], best[closing:]
    for turn in range(min(task.max_delegations+1,task.budget.max_experiments)):
        if stop_reason(task,budget,max(0,turn-1)):
            break
        source=best
        if turn:
            constraints = []
            if "std::sort" in best:
                constraints.append("Explore an algorithm that omits std::sort entirely; the harness will verify whether order matters.")
            revision=ask(f"native-revision-{turn}",
                "Analyze the return value: eliminate expensive work whose result is not needed. Consider loop fusion, dead computation elimination, and order-independent reductions. Prefer a single pass over input when the return value permits it. Preserve the full function signature and all edge cases. " +
                ("Return ONLY the statements inside the function body, no declaration, includes or outer braces. Use the existing parameters and return type." if body_only else "Return the complete C++ file."),{"goal":task.goal,"domain":task.domain,
                "file":editable,"current_source":best,"experiment_constraints":constraints,"feedback":feedback},Revision)
            code = revision.replacement.strip()
            fence = re.fullmatch(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)\n```",code,re.S|re.I)
            if fence:
                code=fence.group(1)
            if body_only:
                declaration=prefix.splitlines()[-1].split("(")[0].split()[-1]
                function=re.search(r"\b"+re.escape(declaration)+r"\s*\([^{}]*\)\s*\{",code)
                if function and code.rstrip().endswith("}"):
                    code=code[function.end():code.rfind("}")]
                source=prefix+"\n"+code+"\n"+suffix
            else:
                source=code
            (folder/f"attempt-{turn}.txt").write_text(source,encoding="utf8")
            emit("hypothesis",round=turn+1,summary=revision.hypothesis)
        key=f"native-{turn}"
        emit("execution",round=turn+1,summary="Compile and measure",observation_id=key)
        out=execute_isolated(registry,budget,key,measure,{"files":files,"editable":editable,"entry":entry,"source":source})
        evidence[key]=out
        emit("validation",round=turn+1,summary=str(out.get("median_ns",out.get("error"))),outcome=out,observation_id=key)
        if not turn:
            if "median_ns" not in out:
                return result("failed",out.get("error","Baseline failed"))
            baseline=best_ns=out["median_ns"]
            best_samples=out["samples_ns"]
        elif "median_ns" in out and max(out["samples_ns"]) < min(best_samples):
            best,best_ns=source,out["median_ns"]
            best_samples=out["samples_ns"]
            accepted.write_text(best,encoding="utf8")
            feedback.append({"decision":"keep","median_ns":best_ns})
        else:
            feedback.append({"decision":"revert","error":out.get("error"),"median_ns":out.get("median_ns"),"rejected_source":source[:1500]})
            emit("revision",round=turn+1,summary=str(feedback[-1]))
        if not turn:
            feedback.append({"baseline_ns":baseline})
    improved=best_ns is not None and best_ns<baseline
    return result("reported" if improved else "inconclusive",
                  f"Baseline {baseline} ns, retained {best_ns} ns, speedup {baseline/best_ns:.3f}x" if baseline else "No measurement",
                  list(evidence))

