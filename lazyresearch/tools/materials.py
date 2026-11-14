from pydantic import Field

from ..models import Record


class ReadMaterial(Record):
    file_id: str = ""
    offset: int = Field(default=0, ge=0)
    query: str = Field(default="", max_length=200)


def read_material(root, task, args):
    text = task["goal"]
    if args.file_id:
        if not any(f["id"] == args.file_id for f in task.get("files", [])):
            raise ValueError("Unknown task file")
        text = (root / "inputs" / args.file_id).read_text(encoding="utf-8-sig")
    observation = {"verdict": "observed", "source": args.file_id or "task", "length": len(text)}
    start = args.offset
    if args.query:
        start = text.find(args.query, start)
        if start < 0:
            return {**observation, "match": False, "query": args.query}
    return {**observation, "offset": start, "excerpt": text[start:start+1600]}
