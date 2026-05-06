"""Stop hook: block Claude from finishing if pytest fails."""
import sys
import json
import subprocess
from pathlib import Path

project = Path("C:/Users/Andy/Documents/loam")
pytest = Path.home() / ".local" / "bin" / "pytest.exe"
tests_dir = project / "tests"

if not tests_dir.exists() or not pytest.exists():
    sys.exit(0)

result = subprocess.run(
    [str(pytest), str(project), "-q", "--tb=short"],
    capture_output=True,
    text=True,
)
output = (result.stdout + result.stderr).strip()

if result.returncode != 0:
    print(json.dumps({
        "decision": "block",
        "reason": f"Tests failed — fix before finishing:\n\n{output}",
    }))

sys.exit(0)
