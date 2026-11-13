import argparse
import json
from pathlib import Path

from .configuration import load_model_config
from .models import ResearchTask


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 LazyResearch 研究闭环")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--goal")
    source.add_argument("--task", type=Path)
    source.add_argument("--resume")
    parser.add_argument("--state-dir", type=Path, default=Path(".lazyresearch"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model-config", type=Path)
    args = parser.parse_args()
    runner = load_model_config(args.model_config).runner(args.state_dir)
    if args.resume:
        run_id = args.resume
    else:
        task = (ResearchTask.model_validate_json(args.task.read_bytes()) if args.task
                else ResearchTask(goal=args.goal))
        run_id = runner.create(task)
    runner.run(run_id)
    state = runner.snapshot(run_id)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_bytes(runner.artifacts(run_id))
    return int(state["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
