"""Compile and test an uploaded native project inside an offline disposable container."""
import shlex
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import uuid
from typing import Literal

from pydantic import Field
from ..models import Record


class NativeTrial(Record):
    sources: list[str] = Field(min_length=1,max_length=12)
    language: Literal["c","cpp"] = "cpp"
    arguments: list[str] = Field(default_factory=list,max_length=30)
    edit_file_id: str = ""
    replacement: str = Field(default="",max_length=32000)


def native_trial(root, task, args):
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Native trials require Docker and the local gcc:13 image")
    files = task.get("files", [])
    ids = {f["id"] for f in files}
    if any(i not in ids for i in args.sources) or (args.edit_file_id and args.edit_file_id not in ids):
        raise ValueError("Select attached source IDs")
    with tempfile.TemporaryDirectory(dir=root) as temp:
        folder = Path(temp).resolve()
        paths = {}
        for f in files:
            rel = PurePosixPath(f.get("archive_path", f["name"]))
            if rel.is_absolute() or ".." in rel.parts or any(":" in part or "\\" in part for part in rel.parts):
                raise ValueError("Invalid archive path")
            dest = (folder / rel).resolve()
            if not dest.is_relative_to(folder) or dest.exists():
                raise ValueError("Ambiguous project path")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if f["id"] == args.edit_file_id:
                dest.write_text(args.replacement,encoding="utf8")
            else:
                shutil.copyfile(root / "inputs" / f["id"], dest)
            paths[f["id"]] = "/project/" + rel.as_posix()
        name = "research-" + uuid.uuid4().hex
        compiler, standard = ("g++","-std=c++17") if args.language=="cpp" else ("gcc","-std=c17")
        # Keep filenames and program arguments out of shell source.
        command = shlex.join([compiler,standard,"-O3","-DNDEBUG",*[paths[i] for i in args.sources],"-o","/tmp/trial"])
        command += " && exec " + shlex.join(["/tmp/trial", *args.arguments])
        try:
            result = subprocess.run([docker,"run","--rm","--pull=never","--name",name,"--network=none",
                "--read-only","--cap-drop=ALL","--security-opt=no-new-privileges","--user","65534:65534",
                "--pids-limit=48","--memory=512m","--cpus=1","--tmpfs","/tmp:exec,size=96m",
                "--mount",f"type=bind,src={folder},dst=/project,readonly","-w","/project",
                "gcc:13","sh","-c","ulimit -t 20; " + command],capture_output=True,timeout=30)
            output = (result.stdout+result.stderr)[-5000:].decode(errors="replace")
            return {"verdict":"observed" if result.returncode==0 else "refuted",
                    "exit_code":result.returncode,"output":output}
        finally:
            subprocess.run([docker,"rm","-f",name],capture_output=True,timeout=5)

