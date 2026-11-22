"""Run backend/integration tests without using the configured archive."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="paperlab-tests-") as folder:
        store = Path(folder)
        env = {
            **os.environ,
            "DATA_ROOT": str(store / "data"),
            "PHYSICS_ARCHIVE_DB": str(store / "archive.db"),
            "PHYSICS_OUTPUT_BASE": str(store / "Outputs"),
            "PIPELINE_CONFIG": str(ROOT / "config.yaml"),
            "TMPDIR": folder,
            "TEMP": folder,
            "TMP": folder,
            "PYTHONUTF8": "1",
        }
        sys.exit(subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "importer_EJEE/tests/", *sys.argv[1:]],
            cwd=ROOT, env=env,
        ).returncode)
