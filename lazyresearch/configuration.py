import os
import tomllib
from pathlib import Path

from pydantic import Field, ValidationError

from .model_gateway import ChatGateway, Endpoint, Prompts
from .models import Record
from .runner import Runner


class ModelConfig(Record):
    local: Endpoint = Field(default_factory=Endpoint)
    cloud: Endpoint = Field(default_factory=Endpoint)
    prompts: Prompts = Field(default_factory=Prompts)

    def runner(self, root: Path, **kwargs) -> Runner:
        local = self.local
        cloud = self.cloud
        local_key = local.api_key.get_secret_value().strip() or os.environ.get(local.api_key_env, "").strip()
        cloud_key = cloud.api_key.get_secret_value().strip() or os.environ.get(cloud.api_key_env, "").strip()
        local_ready = bool(local.enabled and local.base_url and local.model and self.prompts.local
                           and (not local.api_key_env or local_key))
        cloud_ready = bool(cloud.enabled and cloud.base_url and cloud.model and cloud_key
                           and (self.prompts.planning or self.prompts.diagnosis))
        return Runner(
            root, prompts=self.prompts, **kwargs,
            local_gateway=ChatGateway(local, local_key, local=True) if local_ready else None,
            gateway=ChatGateway(cloud, cloud_key) if cloud_ready else None,
        )


def load_model_config(path: Path | None = None) -> ModelConfig:
    configured = path if path is not None else os.environ.get("LAZYRESEARCH_MODEL_CONFIG")
    source = Path(configured) if configured is not None else Path("models.toml")
    if configured is None and not source.exists():
        return ModelConfig()
    try:
        with source.open("rb") as file:
            return ModelConfig.model_validate(tomllib.load(file))
    except ValidationError as error:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in error.errors())
        raise ValueError(f"模型配置字段无效：{fields}") from None
    except tomllib.TOMLDecodeError:
        raise ValueError("模型配置的 TOML 语法无效") from None
