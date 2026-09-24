import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


os.environ["HR_DATA_DIR"] = os.environ.get("HR_DATA_DIR") or tempfile.mkdtemp(prefix="hr-startup-")
os.environ["HR_NO_BROWSER"] = "1"
os.environ["HR_MODE"] = "standalone"

import server
server.init()
print("STARTUP SAFETY: PASS")