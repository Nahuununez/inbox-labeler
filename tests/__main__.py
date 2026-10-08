"""Run every test module in its own process: python -m tests

Each module is a plain script with asserts and fake Gmail/Gemini clients, so it
needs no credentials and makes no network calls. Separate processes keep the
monkeypatching of one module from leaking into another.
"""

import os
import subprocess
import sys
from pathlib import Path

# Real credentials in the environment must not leak into the tests.
SCRUBBED = (
    "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_CONFIDENCE_THRESHOLD",
    "USE_GEMINI", "RULES_PATH", "GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY",
)

here = Path(__file__).resolve().parent
env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
modules = sorted(p.stem for p in here.glob("test_*.py"))
failed = []
for name in modules:
    result = subprocess.run(
        [sys.executable, "-m", f"tests.{name}"],
        cwd=here.parent, env=env, capture_output=True, text=True,
    )
    print(("PASS" if result.returncode == 0 else "FAIL"), name)
    if result.returncode:
        failed.append(name)
        print(result.stdout[-2000:], result.stderr[-2000:])
print(f"\n{len(modules) - len(failed)}/{len(modules)} test modules passed")
sys.exit(1 if failed else 0)
