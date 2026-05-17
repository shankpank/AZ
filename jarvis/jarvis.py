"""Jarvis main app with UI, speech loop, wake modes, and self-test."""
import argparse
import asyncio
import datetime
import os
import struct
import sys
import threading
import time
import webbrowser

import edge_tts
import numpy as np
import pygame
import pyaudio
import pyttsx3
import speech_recognition as sr
from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("ERROR: set GEMINI_API_KEY in jarvis/.env")
    sys.exit(1)
os.environ["GOOGLE_API_KEY"] = API_KEY

import jarvis_tools

WORKDIR = os.path.dirname(os.path.abspath(__file__))
EDGE_VOICE = "en-GB-RyanNeural"
CLAP_RMS_THRESHOLD = 3500
CLAPS_TO_WAKE = 2
CLAP_WINDOW_SEC = 1.5

_lock = threading.Lock()
_state = {"mode": "idle", "subtitle": "", "show_map": False, "markers": [], "image_url": None, "tick": 0}


def set_state(**kw):
    with _lock:
        _state.update(kw)
        _state["tick"] += 1


def set_mode(mode: str, subtitle: str = ""):
    set_state(mode=mode, subtitle=subtitle)


app = Flask(__name__)


@app.route("/")
def home():
    return send_from_directory(WORKDIR, "jarvis_ui.html")


@app.route("/state")
def state():
    with _lock:
        return jsonify(_state)


pygame.mixer.init()
_pytts = pyttsx3.init()


async def _edge_save(text: str, out_path: str):
    await edge_tts.Communicate(text, EDGE_VOICE).save(out_path)


def speak(text: str):
    print(f"JARVIS: {text}")
    set_mode("speaking", text)
    out = os.path.join(WORKDIR, "_speech.mp3")
    try:
        asyncio.run(_edge_save(text, out))
        pygame.mixer.music.load(out)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.unload()
    except Exception:
        _pytts.say(text)
        _pytts.runAndWait()
    set_mode("idle", "")


def listen() -> str:
    set_mode("listening", "Listening...")
    rec = sr.Recognizer()
    with sr.Microphone() as src:
        rec.adjust_for_ambient_noise(src, duration=0.5)
        try:
            audio = rec.listen(src, timeout=6, phrase_time_limit=12)
        except sr.WaitTimeoutError:
            set_mode("idle", "")
            return ""
    set_mode("thinking", "Processing...")
    try:
        text = rec.recognize_google(audio)
        print("YOU:", text)
        return text
    except Exception:
        return ""


def confirm_with_user(action_description: str) -> bool:
    speak(f"Approval needed. I am about to {action_description}. Say yes to confirm or no to cancel.")
    response = listen().lower().strip()
    yes = any(w in response for w in ["yes", "yeah", "approve", "confirm", "go ahead", "ok", "okay"])
    no = any(w in response for w in ["no", "cancel", "stop", "abort"])
    if yes and not no:
        speak("Confirmed")
        return True
    speak("Cancelled")
    return False


def wait_for_wake_signal() -> str:
    pv_key = os.getenv("PICOVOICE_ACCESS_KEY")
    porcupine = None
    if pv_key:
        try:
            import pvporcupine

            porcupine = pvporcupine.create(access_key=pv_key, keywords=["jarvis"])
        except Exception:
            porcupine = None

    sample_rate = porcupine.sample_rate if porcupine else 16000
    frame_length = porcupine.frame_length if porcupine else 512

    pa = pyaudio.PyAudio()
    stream = pa.open(rate=sample_rate, channels=1, format=pyaudio.paInt16, input=True, frames_per_buffer=frame_length)
    set_mode("idle", "Clap twice OR say Jarvis" if porcupine else "Clap twice to wake")

    clap_times, last = [], 0.0
    try:
        while True:
            raw = stream.read(frame_length, exception_on_overflow=False)
            samples = np.frombuffer(raw, dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
            now = time.time()
            if rms > CLAP_RMS_THRESHOLD and (now - last) > 0.2:
                clap_times.append(now)
                last = now
                clap_times = [t for t in clap_times if now - t < CLAP_WINDOW_SEC]
                if len(clap_times) >= CLAPS_TO_WAKE:
                    return "clap"
            if porcupine:
                pcm = struct.unpack_from("h" * frame_length, raw)
                if porcupine.process(pcm) >= 0:
                    return "voice"
    finally:
        stream.close()
        pa.terminate()
        if porcupine:
            porcupine.delete()


def build_agent():
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)
    memory = MemorySaver()
    prompt = (
        "You are Jarvis, concise and useful. Use tools autonomously. "
        "Keep spoken replies short. Use verify/ask clarifying questions when uncertain."
    )
    return create_react_agent(llm, jarvis_tools.ALL_TOOLS, checkpointer=memory, prompt=prompt)


def start_ui():
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False), daemon=True).start()
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")


def self_test():
    print("[Self-test] Starting basic checks...")
    print("time tool:", jarvis_tools.get_current_time.invoke({}))
    print("memory write:", jarvis_tools.remember.invoke({"fact": "self-test fact"}))
    print("memory read:", jarvis_tools.recall_memories.invoke({"filter_text": "self-test"}))
    print("weather:", jarvis_tools.get_weather.invoke({"location": "New York"}))
    print("[Self-test] completed")


def main(run_self_test: bool = False):
    jarvis_tools.init_ui_hooks(set_state, set_mode)
    jarvis_tools.init_approval_hook(confirm_with_user)
    if run_self_test:
        self_test()
        return

    start_ui()
    agent = build_agent()
    speak("Jarvis online. Clap twice or say Jarvis to talk.")
    while True:
        trigger = wait_for_wake_signal()
        print(f"[woke via {trigger}]")
        q = listen().strip()
        if not q:
            continue
        if q.lower().rstrip(".!?,") in {"exit", "quit", "goodbye", "good night", "stop jarvis", "bye"}:
            speak("Goodbye")
            break
        set_mode("thinking", "Thinking...")
        try:
            r = agent.invoke({"messages": [("user", q)]}, config={"configurable": {"thread_id": "jarvis-main"}})
            speak(r["messages"][-1].content.strip())
        except Exception as e:
            speak(f"I hit an error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="Run non-interactive checks for tools and setup")
    args = parser.parse_args()
    main(run_self_test=args.self_test)
