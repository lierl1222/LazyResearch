import subprocess
import sys


def test_run_resume_reproduce_commands_are_exposed():
    for command in ("run", "resume", "reproduce", "stop"):
        result = subprocess.run([sys.executable, "-m", "lazyresearch.science", command, "--help"],
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert "--run-dir" in result.stdout
