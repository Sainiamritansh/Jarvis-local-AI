"""
voice_feedback.py
-----------------
Spoken acknowledgement for the jarvis-selenium project.

    you say "Alexa"  ->  JARVIS says "Yes?" out loud

No beep, no chime, no tone: the AI's voice IS the feedback.

It also fixes the two things that break a spoken ack on a laptop:

  * is_mic_muted()      -> True while he is talking AND for a short settle delay
                           afterwards, so the wake word can never score his own voice
  * drain_microphone()  -> throws away the audio the device buffered while he talked,
                           so his "Yes?" can never be transcribed as YOUR command

TTS source: it reuses voice_engine.speak() - the engine your project already has,
so there is nothing new to install. A local pyttsx3 engine is only built if
voice_engine.py cannot be imported at all.
"""

from __future__ import annotations

import queue
import threading
import time

# --------------------------------------------------------------------- config
ACK_TEXT      = "Yes?"     # what the AI answers when it hears the wake word
                           # (try "Yes!?" if you want it more eager)
ACK_RATE      = 185        # words per minute  - local fallback engine only
ACK_VOLUME    = 1.0        # 0.0 .. 1.0        - local fallback engine only
PREFER_VOICE  = "zira"     # substring of a Windows voice name; None = default voice
ACK_COOLDOWN  = 0.35       # settle delay: seconds the mic stays ignored after he stops
DEBUG         = True       # prints [voice_feedback] ... lines

# Safety net: if the recognizer hands back nothing but the ack itself, treat it as
# silence. Only ever matches on the exact word, so a real "yes" command after a
# different question is not affected.
IGNORE_ACK_TEXTS = ("yes",)

# Optional: if you would rather pass the function in explicitly (e.g. from main.py)
# instead of letting this module import voice_engine, set it here:
#     import voice_engine
#     EXTERNAL_SPEAK = voice_engine.speak
EXTERNAL_SPEAK = None

# --------------------------------------------------------------------- state
_speak_lock   = threading.Lock()      # only one utterance at a time
_engine_lock  = threading.Lock()
_speaking     = False                 # True while an utterance is in progress
_mute_until   = 0.0                   # mic is ignored until this timestamp
_local_engine = None                  # pyttsx3, built only as a last resort
_speak_func   = None                  # resolved callable
_worker       = None
_tts_queue: "queue.Queue[str]" = queue.Queue(maxsize=8)


def _log(msg: str) -> None:
    if DEBUG:
        print(f"[voice_feedback] {msg}")


# ------------------------------------------------------------------- mic gate
def is_mic_muted() -> bool:
    """True while the AI is speaking and for ACK_COOLDOWN seconds after it stops."""
    return _speaking or time.time() < _mute_until


def mic_muted_for(seconds: float) -> None:
    """Push the mute window further into the future."""
    global _mute_until
    _mute_until = max(_mute_until, time.time() + float(seconds))


def mute_seconds_left() -> float:
    """How long the mic still needs to be ignored (0.0 when live)."""
    return max(0.0, _mute_until - time.time())


# ----------------------------------------------------------------- TTS source
def _local_speak(text: str) -> None:
    """Last-resort engine. Only used when voice_engine.py is not importable."""
    global _local_engine
    with _engine_lock:
        if _local_engine is None:
            import pyttsx3
            eng = pyttsx3.init()                      # SAPI5 on Windows
            eng.setProperty("rate", ACK_RATE)
            eng.setProperty("volume", ACK_VOLUME)
            if PREFER_VOICE:
                try:
                    for v in (eng.getProperty("voices") or []):
                        if PREFER_VOICE.lower() in (getattr(v, "name", "") or "").lower():
                            eng.setProperty("voice", v.id)
                            break
                except Exception as exc:
                    _log(f"voice selection skipped: {exc}")
            _local_engine = eng
            _log("local TTS engine built")
        eng = _local_engine
    eng.say(text)
    eng.runAndWait()                                  # blocks until fully spoken


def _resolve_speak():
    """Pick the voice: yours first, a local one only if yours is missing."""
    global _speak_func
    if _speak_func is not None:
        return _speak_func
    if EXTERNAL_SPEAK is not None:
        _speak_func = EXTERNAL_SPEAK
        _log("using the engine passed in via EXTERNAL_SPEAK")
        return _speak_func
    try:
        # Lazy import on purpose: voice_engine imports this module, so importing it
        # at file scope would be circular.
        from voice_engine import speak as project_speak
        _speak_func = project_speak
        _log("using voice_engine.speak()")
        return _speak_func
    except Exception as exc:
        _log(f"voice_engine.speak() unavailable ({exc}) - building a local engine")
    _speak_func = _local_speak
    return _speak_func


def prewarm() -> None:
    """Call ONCE at startup. A no-op when your own voice engine is in use (it is
    already warm, because you speak the greeting before the loop)."""
    func = _resolve_speak()
    if func is not _local_speak:
        _log("prewarm skipped: project voice engine already in use")
        return
    try:
        func(" ")                     # silent: exercise the pipeline, say nothing
        mic_muted_for(0.05)
        _log("local TTS pre-warmed")
    except Exception as exc:
        _log(f"prewarm failed ({exc}) - falling back to text output only")


# -------------------------------------------------------------------- speaking
def _speak_blocking(text: str) -> float:
    """Say `text` out loud, blocking until it finishes. Never raises."""
    global _speaking, _mute_until
    if not text:
        return 0.0
    started = time.time()

    _mute_until = max(_mute_until, started)     # gate closes before the first phoneme
    _speaking = True
    try:
        with _speak_lock:
            _resolve_speak()(text)              # returns only when the voice has stopped
    except Exception as exc:
        _log(f"speak failed: {exc}")
        print(f"JARVIS: {text}")                # never lose the feedback
    finally:
        _speaking = False
        mic_muted_for(ACK_COOLDOWN + 0.15)      # settle delay before the mic goes live

    elapsed = time.time() - started
    _log(f"said {text!r} in {elapsed:.2f}s")
    return elapsed


def say(text: str) -> float:
    """Speak now, on the calling thread. Blocks until the voice has stopped."""
    return _speak_blocking(text)


def say_ack() -> float:
    """The wake-word acknowledgement - the AI answers out loud."""
    return _speak_blocking(ACK_TEXT)


def _worker_loop() -> None:
    while True:
        text = _tts_queue.get()
        try:
            _speak_blocking(text)
        finally:
            _tts_queue.task_done()


def say_async(text: str) -> bool:
    """Queue a longer sentence so the main loop is not blocked. False if busy."""
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_worker_loop, name="jarvis-tts", daemon=True)
        _worker.start()
    try:
        _tts_queue.put_nowait(text)
        return True
    except queue.Full:
        _log("tts queue full - dropped")
        return False


def stop_speaking() -> None:
    """Cut an utterance short (e.g. when the user says 'stop')."""
    try:
        if _local_engine is not None:
            _local_engine.stop()
        elif hasattr(_speak_func, "stop"):
            _speak_func.stop()
    except Exception as exc:
        _log(f"stop failed: {exc}")
    mic_muted_for(ACK_COOLDOWN)


def looks_like_ack(text: str) -> bool:
    """True when a transcript is nothing but the ack - i.e. the mic heard the AI."""
    if not text:
        return False
    cleaned = "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.split()) in IGNORE_ACK_TEXTS


# --------------------------------------------------------------- mic draining
def drain_microphone(stream) -> int:
    """Discard audio already buffered in the mic input queue.

    PyAudio streams expose get_read_available(); anything else is a no-op, because
    blindly calling read() on a blocking stream would hang the loop.
    Returns the number of frames thrown away."""
    if stream is None:
        return 0
    dropped = 0
    try:
        if hasattr(stream, "get_read_available"):
            pending = stream.get_read_available()
            guard = 0
            while pending > 0 and guard < 200:
                stream.read(min(pending, 8192), exception_on_overflow=False)
                dropped += pending
                pending = stream.get_read_available()
                guard += 1
        else:
            _log("drain_microphone: stream has no get_read_available() - skipped")
    except Exception as exc:
        _log(f"drain failed: {exc}")
    return dropped


if __name__ == "__main__":
    # Manual check:  python voice_feedback.py
    prewarm()
    print(f"Speaking {ACK_TEXT!r} ...")
    say_ack()
    print(f"Mic muted for another {mute_seconds_left():.2f}s")
