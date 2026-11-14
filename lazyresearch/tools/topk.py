"""Execute the reviewed Top-K starter only after checking its complete contents."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from ..models import Record

ASSETS = Path(__file__).with_name("topk_assets")


class BenchmarkArgs(Record):
    pass


class CandidateChoice(Record):
    candidate: str
    hypothesis: str


def matches(files):
    expected = json.loads((ASSETS/"manifest.json").read_text())
    return sorted(f.get("archive_path","") for f in files) == sorted(expected)


def prepare(root, task):
    expected = json.loads((ASSETS/"manifest.json").read_text())
    files = task["files"]
    if not matches(files):
        raise ValueError("Unsupported benchmark manifest")
    work = root/"topk"
    for f in files:
        name = f["archive_path"]
        content = (root/"inputs"/f["id"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected[name]:
            raise ValueError("Starter checksum mismatch: "+name)
        dest = work/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(content)
    project = work/"LLM_TopK_Agent_Benchmark"
    if not shutil.which("g++"):
        raise ValueError("GCC C++17 is unavailable")
    candidate = project/"src/candidate.hpp"
    return project,candidate


def measure(root,payload):
    project,candidate=prepare(root,payload["task"])
    candidate.write_text(payload["source"],encoding="utf8")
    output=project/"results"/(payload["phase"]+".json")
    proc=subprocess.run([sys.executable,"scripts/run_all.py","--suite",payload["suite"],"--repeats","9",
                         "--output",str(output.resolve())],cwd=project,capture_output=True,timeout=75)
    if proc.returncode:
        raise ValueError(proc.stderr.decode(errors="replace")[-800:])
    d=json.loads(output.read_text())
    return {**{k:d[k] for k in ("correctness","geomean_speedup","geomean_speedup_vs_strong","wall_time_seconds_including_build")},
            "verdict":"observed"}


def benchmark(root,task,args):
    return measure(root,dict(task=task,source=(ASSETS/"sift.hpp").read_text(),phase="candidate",suite="dev"))


def search(task,material,registry,budget,emit,result,evidence,ask=None):
    from ..iteration import stop_reason
    from ..science.budget import BudgetExceeded
    from ..science.execution import execute_isolated
    from ..research_review import review_evidence
    project,candidate=prepare(registry.root,material)
    best=candidate.read_text(encoding="utf8")
    heap=(ASSETS/"sift.hpp").read_text(encoding="utf8")
    best_score=0
    reserve=int(task.budget.max_experiments>=2)
    checked=[]
    def trial(label,source,suite,turn):
        key=f"topk-{label}"
        emit("execution",round=turn,summary=label,observation_id=key)
        out=execute_isolated(registry,budget,key,measure,dict(task=material,source=source,phase=label,suite=suite))
        evidence[key]=out
        emit("validation",round=turn,observation_id=key,summary=out.get("correctness",out.get("error")),outcome=out)
        if ask:
            review_evidence(ask, registry, emit, key, task.goal, label, out,
                            prior=list(evidence.values())[-4:], round=turn)
        return out
    reason=""
    try:
        candidates = dict(variants(best,heap))
        for turn in range(1, len(candidates) + 1):
            reason=stop_reason(task,budget,turn-1,reserve)
            if reason:
                break
            label = next(iter(candidates))
            hypothesis = label
            if ask:
                instruction = ('根据真实开发集结果与独立评审选择下一个尚未执行的候选。candidate 必须来自 candidates。'
                               '优先保证正确性，再最大化强基线加速比，解释选择理由。')
                context = {'goal': task.goal, 'candidates': list(candidates), 'observations': evidence,
                           'reviews': registry.list('research_reviews')[-3:]}
                choice = None
                for attempt in ("", "-repair"):
                    try:
                        choice = ask(f'topk-director-{turn}{attempt}', instruction, context, CandidateChoice,
                                     complex_step=bool(attempt))
                    except BudgetExceeded:
                        raise
                    except RuntimeError:
                        break
                    if choice.candidate in candidates:
                        break
                    context = {**context, "rejected_candidate": choice.candidate}
                    instruction += (f" 刚才选择了无效候选 {choice.candidate!r}，它不在剩余 candidates 中。"
                                    "必须从剩余 candidates 里选择一个。")
                if choice and choice.candidate in candidates:
                    label, hypothesis = choice.candidate, choice.hypothesis
                else:
                    emit("revision", round=turn,
                         summary=f"本机补选 · 决策 Agent 未给出有效候选，按顺序测试 {label}。")
            source = candidates.pop(label)
            emit("hypothesis",round=turn,summary=hypothesis)
            out=trial(label,source,"dev",turn)
            score=out.get("geomean_speedup_vs_strong",0)
            if score>best_score:
                best,best_score=source,score
            checked.append(label)
            emit("revision",round=turn,summary=f"当前最佳开发集强基线加速比 {best_score:.3f}x")
        else:
            reason="已测完当前工具支持的不同候选"
        if reserve and best_score and not budget.stop_requested() and budget.remaining_time()>0:
            final=trial("final",best,"eval",len(checked)+1)
            reason += "；独立评估 "+str(final.get("geomean_speedup_vs_strong",final.get("error")))
    except BudgetExceeded as error:
        reason=str(error)
    finally:
        candidate.write_text(best,encoding="utf8")
    return result("stopped" if budget.stop_requested() else "reported" if best_score else "inconclusive",
                  f"{reason}。开发集共测 {len(checked)} 个方案，最佳强基线加速比 {best_score:.3f}x。",
                  [k for k,v in evidence.items() if v.get("verdict")])


def variants(original, heap):
    yield "initial",original
    yield "candidate",heap
    marker="    std::vector<TokenScore> heap;"
    for cutoff in (1,4,8,16,32,64,128,256,512):
        # For small K buffer survivors, partition in batches and sort only the winners.
        branch = """
    if (k <= LIMIT) {
        std::vector<TokenScore> buf;
        buf.reserve(2*k);
        float floor = -std::numeric_limits<float>::infinity();
        for (std::size_t i=0;i<vocab;++i) {
            if (buf.size() >= k && logits[i] < floor) continue;
            buf.push_back({static_cast<std::uint32_t>(i),logits[i]});
            if (buf.size()==2*k) {
                std::nth_element(buf.begin(),buf.begin()+k-1,buf.end(),rank_before);
                buf.resize(k);
                floor=buf.back().score;
            }
        }
        std::sort(buf.begin(),buf.end(),rank_before);
        buf.resize(k);
        return buf;
    }
""".replace("LIMIT",str(cutoff))
        yield f"partition-{cutoff}",heap.replace("#include <algorithm>","#include <algorithm>\n#include <limits>").replace(marker,branch+marker)
