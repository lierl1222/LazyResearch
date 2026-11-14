"""Load trusted project tools for one research run."""
import re
import tomllib
from importlib import import_module, invalidate_caches
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .models import Record


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "tools.toml"


class Tool(Record):
    material: str
    label: str
    purpose: str
    module: str
    argument_model: str = Field(alias="schema")
    function: str
    prefer_first: bool = False

    def resolve(self):
        package = import_module(f".tools.{self.module}", __package__)
        schema = getattr(package, self.argument_model)
        execute = getattr(package, self.function)
        if not isinstance(schema, type) or not issubclass(schema, BaseModel) or not callable(execute):
            raise ValueError("Tool requires a Pydantic schema and a callable")
        return schema, execute


def load_tools(path=DEFAULT_CONFIG):
    try:
        with Path(path).open("rb") as stream:
            configured = tomllib.load(stream).get("tools")
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError("无法读取工具配置，请检查 configs/tools.toml。") from error
    if not isinstance(configured, dict):
        raise ValueError("工具配置缺少有效的 tools 表。")
    invalidate_caches()
    tools = {}
    for name, spec in configured.items():
        try:
            tool = Tool.model_validate(spec)
            identifiers = (name, tool.module, tool.argument_model, tool.function, tool.material)
            if not all(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", item) for item in identifiers):
                raise ValueError("Expected simple identifiers")
            tool.resolve()
        except (ValidationError, ValueError, ImportError, AttributeError) as error:
            raise ValueError(f"工具配置无效：{name}") from error
        tools[name] = tool
    return tools


def execute_tool(root, payload):
    if "generated_source" in payload:
        from .tools.generated import evaluate
        return {"verdict":"observed","value":evaluate(payload["generated_source"],payload["arguments"]["inputs"])}
    tool = Tool.model_validate(payload["tool_spec"])
    schema, execute = tool.resolve()
    return execute(root, payload["task"], schema.model_validate(payload["arguments"]))
