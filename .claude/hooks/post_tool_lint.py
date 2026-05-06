"""PostToolUse hook: run ruff on Python files after Claude writes or edits them."""
import sys
import json
import subprocess
from pathlib import Path

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path or not file_path.endswith(".py"):
    sys.exit(0)

ruff = Path.home() / ".local" / "bin" / "ruff.exe"
if not ruff.exists():
    sys.exit(0)

result = subprocess.run(
    [str(ruff), "check", file_path],
    capture_output=True,
    text=True,
)
output = (result.stdout + result.stderr).strip()

if output:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"Ruff lint errors in {Path(file_path).name}:\n"
                f"{output}\n\n"
                "Fix these before proceeding."
            ),
        }
    }))

sys.exit(0)
