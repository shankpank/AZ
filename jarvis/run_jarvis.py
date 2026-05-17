"""One-click launcher for Jarvis.
Default: installs deps and runs interactive mode.
Use --self-test to run non-interactive smoke checks.
"""
import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
ENV = ROOT / ".env"


def vpy() -> str:
    return str(VENV / ("Scripts/python.exe" if platform.system().lower().startswith("win") else "bin/python"))


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.check_call(cmd)


def ensure_env_template():
    if ENV.exists():
        return
    ENV.write_text(
        "GEMINI_API_KEY=\nPICOVOICE_ACCESS_KEY=\nGMAIL_USER=\nGMAIL_APP_PASSWORD=\nDEFAULT_LOCATION=New York\n",
        encoding="utf-8",
    )
    print(f"Created {ENV}. Add GEMINI_API_KEY and run again.")


def main(self_test: bool):
    if not VENV.exists():
        run([sys.executable, "-m", "venv", str(VENV)])
    py = vpy()
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", str(REQ)])
    ensure_env_template()
    cmd = [py, str(ROOT / "jarvis.py")]
    if self_test:
        cmd.append("--self-test")
    run(cmd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="Run non-interactive self-test mode")
    args = parser.parse_args()
    main(self_test=args.self_test)
