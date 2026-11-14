import json
import sys
from pathlib import Path

from lazyresearch.science.registry import Registry

root = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/llm-check-custom-0a684547")
r = Registry(root)
for kind in ("science_tools", "hypotheses", "reviews", "decisions", "analyses", "fallback"):
    values = r.list(kind)
    if values:
        print(f"=== {kind} ({len(values)}) ===")
        for v in values:
            print(json.dumps(v, ensure_ascii=False)[:900])
print("=== model_calls ids ===")
for v in r.list("model_calls"):
    print(v["id"], v["role"], v.get("status"), v.get("model"))
print("=== experiments ===")
for v in r.list("experiments"):
    print(v.get("experiment_id"), "verdict:", v.get("verdict"), "value:", json.dumps(v.get("value"))[:300], "error:", v.get("error"))
