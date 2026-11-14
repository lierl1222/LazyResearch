"""Run task-local JS functions in a fresh bounded interpreter without host callbacks."""
import json
from typing import Any

from pydantic import Field
from ..models import Record


class Definition(Record):
    name: str = Field(pattern=r"^custom_[a-z][a-z0-9_]{0,40}$")
    purpose: str = Field(min_length=1,max_length=350)
    source: str = Field(min_length=1,max_length=12000, description="Executable JavaScript arrow function, e.g. x => x.n * 2. Never a URL or file path.")
    example: dict = Field(description="Exactly the input object of the function, e.g. {\"n\":3}; no tool metadata.")
    expected: Any


class Inputs(Record):
    inputs: dict


def evaluate(source, inputs):
    import quickjs
    vm = quickjs.Context()
    vm.set_memory_limit(16 * 1024 * 1024)
    vm.set_max_stack_size(256 * 1024)
    vm.set_time_limit(0.5)
    encoded = json.dumps(inputs, allow_nan=False)
    if len(encoded)>64000:
        raise ValueError("Input exceeds 64000 characters")
    vm.set("inputJSON", encoded)
    output = vm.eval("JSON.stringify((" + source + ")(JSON.parse(inputJSON)))")
    if not isinstance(output,str) or len(output)>16000:
        raise ValueError("Tool must return a bounded JSON value")
    return json.loads(output)


def register(root, task, args):
    try:
        actual = evaluate(args.source, args.example)
    except Exception as error:
        raise ValueError("样例运行失败：" + str(error)[:300] + "；请修正函数后重新提交。") from error
    if actual != args.expected:
        raise ValueError("样例校验未通过：source(example)=" + json.dumps(actual, ensure_ascii=False)[:300]
                         + "，expected=" + json.dumps(args.expected, ensure_ascii=False)[:300]
                         + "；请修正函数或样例，不得只修改 expected 迎合错误实现。")
    return {"verdict": "observed", "registered": args.name, "registration": "pending",
            "scope": "样例校验通过，待真实调用验证后正式注册"}


def invoke(root, task, args):
    raise RuntimeError("Generated tools require their registered definition")

