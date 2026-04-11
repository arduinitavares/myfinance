import os
import shutil
from pathlib import Path


TEST_ROOT = Path(__file__).resolve().parent / ".tmp"
shutil.rmtree(TEST_ROOT, ignore_errors=True)
(TEST_ROOT / "data").mkdir(parents=True, exist_ok=True)

os.environ["MYFINANCE_DATA_DIR"] = str((TEST_ROOT / "data").resolve())
os.environ["MYFINANCE_PROVIDER_CONFIG"] = str((TEST_ROOT / "config.local.yaml").resolve())
