"""Jarvis tool catalog."""
import datetime
import json
import os
import smtplib
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from email.message import EmailMessage

import requests
from google import genai
from google.genai import types
from langchain_core.tools import tool

WORKDIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(WORKDIR, "workspace")
MEMORY_FILE = os.path.join(WORKDIR, "jarvis_memory.json")
os.makedirs(WORKSPACE, exist_ok=True)

GEMINI_MODEL = "gemini-2.5-flash"
gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

set_state = None
set_mode = None
confirm_with_user = None
require_approvals = True


def init_ui_hooks(state_setter, mode_setter):
    global set_state, set_mode
    set_state = state_setter
    set_mode = mode_setter


def init_approval_hook(confirm_fn):
    global confirm_with_user
    confirm_with_user = confirm_fn


def _ui_state(**kwargs):
    if set_state:
        set_state(**kwargs)


def _ui_mode(mode: str, subtitle: str = ""):
    if set_mode:
        set_mode(mode, subtitle)


def _guard(action: str):
    if not require_approvals or confirm_with_user is None:
        return None
    if confirm_with_user(action):
        return None
    return "User declined this action."


def _safe_workspace(path: str) -> str:
    full = os.path.abspath(os.path.join(WORKSPACE, path))
    if not full.startswith(os.path.abspath(WORKSPACE)):
        raise ValueError("Path escapes workspace")
    return full


def _load_mem():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_mem(mems):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mems, f, indent=2)


@tool
def get_current_time() -> str:
    """Return local date and time."""
    return datetime.datetime.now().strftime("%I:%M %p on %A, %B %d, %Y")


@tool
def search_web(query: str) -> str:
    """Search web with Gemini grounding for fresh information."""
    _ui_mode("thinking", f"Searching: {query}")
    try:
        resp = gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=query,
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
        return (resp.text or "").strip() or "No result returned."
    except Exception as e:
        return f"Search failed: {e}"


@tool
def get_weather(location: str = "") -> str:
    """Get weather using Open-Meteo with OSM geocoding."""
    location = location or os.getenv("DEFAULT_LOCATION", "New York")
    try:
        geo = requests.get(
            f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(location)}&format=json&limit=1",
            headers={"User-Agent": "JarvisAssistant/1.0"},
            timeout=12,
        ).json()
        if not geo:
            return f"Could not find location: {location}"
        lat, lon = float(geo[0]["lat"]), float(geo[0]["lon"])
        cur = requests.get(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m,relative_humidity_2m",
            timeout=12,
        ).json().get("current", {})
        return (
            f"Weather in {location}: {cur.get('temperature_2m')}°C, "
            f"humidity {cur.get('relative_humidity_2m')}%, wind {cur.get('wind_speed_10m')} km/h."
        )
    except Exception as e:
        return f"Weather error: {e}"


@tool
def open_website(name_or_url: str) -> str:
    """Open common websites or URL."""
    sites = {
        "youtube": "https://youtube.com",
        "google": "https://google.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
    }
    key = name_or_url.lower().strip()
    url = sites.get(key, name_or_url if name_or_url.startswith("http") else f"https://{name_or_url}")
    webbrowser.open(url)
    return f"Opened {url}"


@tool
def run_python_code(code: str) -> str:
    """Run Python code in isolated process from workspace."""
    refused = _guard(f"run a {len(code.splitlines())}-line Python script")
    if refused:
        return refused
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        temp = f.name
    try:
        r = subprocess.run([sys.executable, temp], capture_output=True, text=True, timeout=25, cwd=WORKSPACE)
        out = (r.stdout or "") + (r.stderr or "")
        return out[:3000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Code timed out after 25 seconds."
    finally:
        try:
            os.unlink(temp)
        except Exception:
            pass


@tool
def write_file(path: str, content: str) -> str:
    """Write file inside workspace."""
    refused = _guard(f"write {len(content)} characters to '{path}'")
    if refused:
        return refused
    try:
        p = _safe_workspace(path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote workspace/{path}"
    except Exception as e:
        return f"Write error: {e}"


@tool
def read_file(path: str) -> str:
    """Read file inside workspace."""
    try:
        with open(_safe_workspace(path), "r", encoding="utf-8") as f:
            return f.read()[:10000]
    except Exception as e:
        return f"Read error: {e}"


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send email through Gmail app password."""
    refused = _guard(f"send an email to {to}")
    if refused:
        return refused
    user = os.getenv("GMAIL_USER")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pw:
        return "Email not configured. Add GMAIL_USER and GMAIL_APP_PASSWORD in .env"
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = user, to, subject
        msg.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pw)
            s.send_message(msg)
        return f"Email sent to {to}."
    except Exception as e:
        return f"Email failed: {e}"


@tool
def remember(fact: str) -> str:
    """Remember user facts permanently."""
    mems = _load_mem()
    mems.append({"fact": fact, "ts": datetime.datetime.now().isoformat()})
    _save_mem(mems)
    return f"Remembered: {fact}"


@tool
def recall_memories(filter_text: str = "") -> str:
    """Recall stored memories."""
    mems = _load_mem()
    if filter_text:
        mems = [m for m in mems if filter_text.lower() in m["fact"].lower()]
    return "\n".join(f"- {m['fact']}" for m in mems[-20:]) if mems else "No memories found."


@tool
def disable_approvals() -> str:
    """Disable sensitive-action confirmations."""
    global require_approvals
    require_approvals = False
    return "Approvals disabled."


@tool
def enable_approvals() -> str:
    """Enable sensitive-action confirmations."""
    global require_approvals
    require_approvals = True
    return "Approvals enabled."


ALL_TOOLS = [
    get_current_time,
    search_web,
    get_weather,
    open_website,
    run_python_code,
    write_file,
    read_file,
    send_email,
    remember,
    recall_memories,
    disable_approvals,
    enable_approvals,
]
