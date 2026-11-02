import base64
import os
import shutil
import subprocess

import speech_recognition as sr
import pyttsx3

recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = True
tts_engine = None
_tts_unavailable_reason = None
# pyttsx3 can return from runAndWait() without playing anything on some
# Windows/Python combinations.  Native Windows speech has proven reliable here.
PREFER_WINDOWS_VOICE = True

_calibrated = False


def _get_tts_engine():
    """Create pyttsx3 lazily so a SAPI problem cannot stop JARVIS starting."""
    global tts_engine, _tts_unavailable_reason

    if tts_engine is not None:
        return tts_engine
    if _tts_unavailable_reason is not None:
        return None

    try:
        tts_engine = pyttsx3.init()
        tts_engine.setProperty("rate", 175)
        tts_engine.setProperty("volume", 1.0)
        return tts_engine
    except Exception as error:
        _tts_unavailable_reason = error
        print(f"(pyttsx3 unavailable: {error}; using Windows voice fallback)")
        return None


def _speak_with_windows_voice(text):
    """Use Windows' built-in speech API when pyttsx3/SAPI cannot initialise."""
    # -EncodedCommand avoids quoting issues for commands containing apostrophes,
    # ampersands, or non-ASCII characters.
    safe_text = str(text).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speaker.Volume = 100; $speaker.Rate = 0; "
        f"$speaker.Speak('{safe_text}')"
    )
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    # PowerShell 7 hosts System.Speech correctly in this environment.  Use it
    # first, with Windows PowerShell retained for machines where it is absent.
    powershell = shutil.which("pwsh.exe") or os.path.join(
        os.environ.get("WINDIR", r"C:\\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def speak(text):
    """Print and audibly speak a reply, including a Windows fallback."""
    message = str(text)
    print(f"JARVIS: {message}")

    if PREFER_WINDOWS_VOICE:
        try:
            _speak_with_windows_voice(message)
            return
        except Exception as error:
            print(f"(Windows speech error: {error}; trying pyttsx3)")

    engine = _get_tts_engine()
    if engine is not None:
        try:
            engine.say(message)
            engine.runAndWait()
            return
        except Exception as error:
            print(f"(pyttsx3 speech error: {error}; using Windows voice fallback)")

    try:
        _speak_with_windows_voice(message)
    except Exception as error:
        print(f"(Windows speech fallback error: {error})")


def listen():
    """Captures one voice command from the mic and returns it as lowercase text."""
    global _calibrated

    with sr.Microphone() as source:
        # Calibrate for background noise once, not on every command.
        if not _calibrated:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            _calibrated = True
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)
        except sr.WaitTimeoutError:
            return ""

    try:
        text = recognizer.recognize_google(audio)
        print(f"You: {text}")
        return text.lower()
    except sr.UnknownValueError:
        print("(didn't catch that)")
        return ""
    except sr.RequestError:
        print("(speech service unavailable, check your internet)")
        return ""
