import os
import sys
import zipfile
import urllib.request
import subprocess
import json
import time
import threading
from datetime import datetime

CLI_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(CLI_DIR, "vosk-model")

def install_deps():
    try:
        import vosk
        import sounddevice
    except ImportError:
        print("[SYSTEM] Installing audio listener dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", "vosk", "sounddevice"], check=True)

def download_model():
    if not os.path.exists(MODEL_DIR):
        print("[SYSTEM] Downloading Vosk offline neural network (~40MB)...")
        zip_path = os.path.join(CLI_DIR, "model.zip")
        # Download the lightweight English model
        urllib.request.urlretrieve("https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip", zip_path)
        print("[SYSTEM] Extracting neural network...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(CLI_DIR)
        os.rename(os.path.join(CLI_DIR, "vosk-model-small-en-us-0.15"), MODEL_DIR)
        os.remove(zip_path)

def listen():
    import vosk
    import sounddevice as sd
    import queue
    import winsound

    q = queue.Queue()
    def callback(indata, frames, time, status):
        if status: print(status, file=sys.stderr)
        q.put(bytes(indata))

    print("[SYSTEM] Loading offline wake-word model...")
    model = vosk.Model(MODEL_DIR)
    samplerate = 16000
    
    print("\n=======================================================")
    print(" 🎧 Ambient Listener ACTIVE.")
    print(" You can minimize this window.")
    print(" Say 'Hey Div' or 'Hey AI' to wake up the assistant.")
    print("=======================================================")

    with sd.RawInputStream(samplerate=samplerate, blocksize=8000, dtype='int16', channels=1, callback=callback):
        rec = vosk.KaldiRecognizer(model, samplerate)
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                text = res.get("text", "")
                
                # Vosk phonetic catches for "Hey Div AI" or variations
                wake_words = ["hey div", "hey dave", "hey did", "hey ai", "div ai", "hey give", "hey def"]
                
                if any(wake in text for wake in wake_words):
                    print(f"\n[WAKE WORD DETECTED] -> '{text}'")
                    # Double beep for audio feedback
                    winsound.Beep(1000, 150) 
                    winsound.Beep(1500, 150) 
                    
                    # Spawn divAI in a new terminal window directly into voice mode
                    cli_path = os.path.join(CLI_DIR, 'divCLI.py')
                    subprocess.Popen(f'start powershell -NoExit -Command "& {sys.executable} {cli_path} --voice"', shell=True)
                    
                    # Pause the ambient listener for 10 seconds to avoid a feedback loop
                    import time
                    time.sleep(10)
                    print("\n[SYSTEM] Resuming ambient listening...")

def scheduler_loop():
    """Background thread: fires notifications every 30 min; extra check at 8 AM."""
    print("[SYSTEM] Background scheduler active.")
    last_morning = ""
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            # Morning briefing toast once at 8 AM
            if now.hour == 8 and last_morning != today:
                last_morning = today
                from div_notify import check_and_notify
                check_and_notify()
            # Every 30 min: check for urgent deadlines
            from div_notify import check_and_notify
            alerts = check_and_notify()
            if alerts:
                print(f"[SCHEDULER] Fired {len(alerts)} alert(s)")
        except Exception as e:
            print(f"[SCHEDULER] Error: {e}")
        time.sleep(1800)  # 30 minutes


if __name__ == "__main__":
    install_deps()
    download_model()
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    listen()
