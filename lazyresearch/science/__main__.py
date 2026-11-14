"""Science CLI. Baseline is a Phase 1 diagnostic, not a completed research run."""
import argparse
import hashlib
import json
import uuid
from pathlib import Path

from .data import generate_demo, prepare_dataset
from .experiments import ExperimentSpec, run_experiment
from .schemas import load_task


def save_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="LazyResearch 表格研究引擎")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("generate-demo")
    demo.add_argument("--output", type=Path, default=Path("data/synthetic_demo.csv"))
    demo.add_argument("--rows", type=int, default=600)
    demo.add_argument("--seed", type=int, default=42)
    baseline = commands.add_parser("baseline", help="Phase 1 基线诊断，不是完整研究循环")
    baseline.add_argument("--config", type=Path, required=True)
    baseline.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="运行角色化表格研究闭环")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--run-dir", type=Path)
    run.add_argument("--llm", choices=["mock", "api"])
    run.add_argument("--model-config", type=Path)
    resume = commands.add_parser("resume")
    resume.add_argument("--run-dir", type=Path, required=True)
    resume.add_argument("--model-config", type=Path)
    replay = commands.add_parser("reproduce")
    replay.add_argument("--run-dir", type=Path, required=True)
    replay.add_argument("--output", type=Path)
    stop = commands.add_parser("stop")
    stop.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate-demo":
        generate_demo(args.output, args.rows, args.seed)
        print(args.output.resolve())
        return
    if args.command == "stop":
        if not (args.run_dir / "registry.sqlite").exists():
            parser.error("Research run does not exist")
        (args.run_dir / "stop.requested").touch()
        print("Stop requested")
        return
    if args.command == "reproduce":
        from .reproduce import reproduce
        output = args.output or Path("runs") / ("replay-" + uuid.uuid4().hex[:12])
        result = reproduce(args.run_dir, output)
        print(json.dumps({"run_dir": str(output.resolve()), **result}, ensure_ascii=False, indent=2))
        return
    if args.command in {"run", "resume"}:
        from ..configuration import load_model_config
        from .graph import ScienceRunner
        from .registry import Registry
        from .schemas import TaskConfig
        if args.command == "resume":
            if not (args.run_dir / "registry.sqlite").exists():
                parser.error("Research run does not exist")
            config = TaskConfig.model_validate(Registry(args.run_dir).get("task"))
            root = args.run_dir
        else:
            config = load_task(args.config)
            if args.llm:
                config.llm.provider = "configured_api" if args.llm == "api" else "mock"
            root = args.run_dir or Path("runs") / uuid.uuid4().hex
            if root.exists():
                parser.error("Run directory exists; use resume or a new directory")
        runner = ScienceRunner(root, config, model_config=load_model_config(args.model_config))
        result = runner.run()
        print(json.dumps({"run_dir": str(root.resolve()), **result}, ensure_ascii=False, indent=2))
        if result.get("error"):
            raise SystemExit(1)
        return
    config = load_task(args.config)
    data = prepare_dataset(config)
    args.output.mkdir(parents=True, exist_ok=False)
    save_json(args.output / "dataset_profile.json", data.profile)
    save_json(args.output / "split_indices.json", data.split_indices)
    results = []
    for model in ["dummy", "logistic"]:
        spec = ExperimentSpec(id=f"baseline-{model}", hypothesis_id="baseline-control",
                              model_name=model, data_features=list(data.X_train.columns),
                              random_seed=config.validation.random_seed)
        result, _ = run_experiment(spec, data, config.objective.top_fraction)
        results.append(result)
    save_json(args.output / "baseline_metrics.json", results)
    save_json(args.output / "run_manifest.json", {
        "mode": "baseline_diagnostic", "complete_research": False,
        "dataset_sha256": data.dataset_hash,
        "config": config.model_dump(),
        "config_sha256": hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
        "test_evaluations": 0,
    })
    print(json.dumps({r["experiment_id"]: r["metrics"] for r in results}, indent=2))


if __name__ == "__main__":
    main()
