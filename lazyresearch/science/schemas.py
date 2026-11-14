from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from ..models import Record


class DatasetConfig(Record):
    path: str
    format: Literal["csv", "parquet"] = "csv"
    target: str
    task_type: Literal["binary_classification"] = "binary_classification"
    forbidden_features: list[str] = Field(default_factory=lambda: ["duration"])
    time_column: str | None = None
    positive_label: str | int | float = 1


class Objective(Record):
    primary_metric: Literal["average_precision"] = "average_precision"
    secondary_metrics: list[str] = Field(default_factory=lambda: ["roc_auc", "f1", "precision_at_k", "lift_at_k"])
    top_fraction: float = Field(default=.2, gt=0, le=1)
    optimization: Literal["maximize"] = "maximize"
    description: str = "预测响应倾向；不作因果收益推断。"
    target_score: float | None = Field(default=None, ge=0, le=1)


class ValidationConfig(Record):
    strategy: Literal["stratified_holdout", "temporal_holdout"] = "stratified_holdout"
    train_fraction: float = Field(default=.6, gt=0, lt=1)
    val_fraction: float = Field(default=.2, gt=0, lt=1)
    test_fraction: float = Field(default=.2, gt=0, lt=1)
    random_seed: int = 42
    bootstrap_samples: int = Field(default=100, ge=20, le=1000)

    @model_validator(mode="after")
    def fractions(self):
        if abs(self.train_fraction + self.val_fraction + self.test_fraction - 1) > 1e-9:
            raise ValueError("train/validation/test fractions must sum to 1")
        return self


class ScienceBudget(Record):
    max_cloud_requests: int | None = Field(default=None, ge=0)
    max_llm_input_tokens: int | None = Field(default=None, ge=0)
    max_llm_output_tokens: int = Field(default=4000, ge=0)
    max_llm_calls: int = Field(default=20, ge=0)
    max_experiments: int = Field(default=12, ge=0)
    max_wall_time_seconds: float = Field(default=900, gt=0)
    max_single_experiment_seconds: float = Field(default=90, gt=0)
    max_cpu_seconds: float = Field(default=600, ge=0)
    max_api_cost_usd: float | None = Field(default=None, ge=0)


class ResearchConfig(Record):
    max_hypotheses: int = Field(default=6, ge=2, le=30)
    min_required_experiments: int = Field(default=3, ge=0)
    no_improvement_patience: int = Field(default=3, ge=1)
    max_iterations: int = Field(default=12, ge=1, le=100)
    allow_advanced_models: bool = True


class LLMConfig(Record):
    provider: Literal["mock", "configured_api"] = "mock"
    model: str | None = None
    allow_mock: bool = False


class TaskConfig(Record):
    project_name: str = "lazyresearch-science"
    dataset: DatasetConfig
    objective: Objective = Field(default_factory=Objective)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    budget: ScienceBudget = Field(default_factory=ScienceBudget)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def load_task(path: Path) -> TaskConfig:
    import os
    import re

    def expand(value):
        if isinstance(value, str):
            def replace(match):
                if match[1] not in os.environ:
                    raise ValueError(f"Missing environment variable: {match[1]}")
                return os.environ[match[1]]
            return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    config = TaskConfig.model_validate(expand(yaml.safe_load(path.read_text(encoding="utf-8"))))
    dataset = Path(config.dataset.path)
    config.dataset.path = str((path.parent / dataset).resolve() if not dataset.is_absolute() else dataset)
    return config
