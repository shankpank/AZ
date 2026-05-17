# Jarvis (Python) — one-command setup

## What you do (only 2 things)
1. Open `jarvis/.env` and paste your free API key:
   - `GEMINI_API_KEY` from https://aistudio.google.com/apikey (free tier).
   - Optional: `PICOVOICE_ACCESS_KEY` from https://console.picovoice.ai/ for wake-word "Jarvis".
2. Run:

```bash
python jarvis/run_jarvis.py
```

That is it. The launcher creates a virtualenv, installs dependencies, and starts Jarvis.

## Test both versions
- **Version A (non-interactive smoke test):**

```bash
python jarvis/run_jarvis.py --self-test
```

This validates setup and core tools without microphone/speaker interaction.

- **Version B (full interactive voice Jarvis):**

```bash
python jarvis/run_jarvis.py
```

This launches the 3D HUD (`http://127.0.0.1:5000`) and voice loop.

## Free APIs and services used
- Gemini API (LLM + grounded search): Google AI Studio free key.
- Open-Meteo (weather): free.
- OpenStreetMap Nominatim (geocoding): free.
- edge-tts (speech output): free.

## Notes
- You need Python 3.10+, a microphone, and speakers for interactive mode.
- If `pyaudio` fails on Windows:

```bash
jarvis\.venv\Scripts\python -m pip install pipwin
jarvis\.venv\Scripts\python -m pipwin install pyaudio
```
