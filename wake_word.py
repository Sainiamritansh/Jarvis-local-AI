import signal
import time
import warnings

import numpy as np
import openwakeword
import pyaudio
from openwakeword.model import Model

import voice_feedback                      # NEW
from commands import execute_command, is_shutdown_command
from voice_engine import listen, speak

# Hide library warnings so the terminal only shows the conversation.
warnings.filterwarnings("ignore")
try:
    import onnxruntime
    onnxruntime.set_default_logger_severity(3)
except Exception:
    pass


SAMPLE_RATE = 16000
FRAME_LENGTH = 1280  # 80 ms, the recommended openWakeWord frame size
DETECTION_THRESHOLD = 0.5


def listen_for_wake_word(keyword="alexa"):
    """Listen continuously and route a spoken command after wake-word detection."""
    model = None
    audio = None
    stream = None
    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    def open_microphone():
        return audio.open(
            rate=SAMPLE_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=FRAME_LENGTH,
        )

    def close_microphone(active_stream):
        if active_stream is None:
            return
        try:
            active_stream.stop_stream()
        except OSError:
            pass  # already stopped or closed
        try:
            active_stream.close()
        except OSError:
            pass  # already closed

    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, request_stop)

    try:
        # Downloads the package's public pretrained model files if they are missing.
        openwakeword.utils.download_models()
        model = Model(
            wakeword_models=[keyword],
            inference_framework="onnx",
        )
        audio = pyaudio.PyAudio()
        stream = open_microphone()

        speak(f"Ready. Say {keyword.replace('_', ' ')}.")
        # NEW: his greeting went out the speakers - bin it before listening.
        voice_feedback.drain_microphone(stream)

        while not stopping:
            # NEW: never read the mic while he is talking. Reading it would feed his
            # own voice to the model, which is how a wake word triggers itself.
            if voice_feedback.is_mic_muted():
                voice_feedback.drain_microphone(stream)
                time.sleep(0.01)                 # don't busy-spin while he speaks
                continue

            pcm = stream.read(FRAME_LENGTH, exception_on_overflow=False)
            frame = np.frombuffer(pcm, dtype=np.int16)
            predictions = model.predict(frame)

            if predictions.get(keyword, 0.0) >= DETECTION_THRESHOLD:
                # NEW: he answers "Yes?" out loud, and the audio he just made is
                # discarded instead of being scored later as your command.
                voice_feedback.say_ack()
                voice_feedback.drain_microphone(stream)

                old_stream, stream = stream, None
                close_microphone(old_stream)
                exit_requested = False

                try:
                    text = listen()

                    if not text or voice_feedback.looks_like_ack(text):
                        continue

                    if is_shutdown_command(text):
                        speak("Shutting down. Goodbye.")
                        exit_requested = True
                    else:
                        speak(execute_command(text))

                except Exception as error:
                    print(f"(command failed: {error})")
                finally:
                    if not stopping and not exit_requested:
                        stream = open_microphone()
                        # NEW: drop whatever landed in the buffer while he was talking.
                        voice_feedback.drain_microphone(stream)
                        # Clear leftover audio so the wake word can't re-trigger itself.
                        if hasattr(model, "reset"):
                            model.reset()

                if exit_requested:
                    break

    except KeyboardInterrupt:
        pass
    finally:
        close_microphone(stream)
        stream = None
        if audio is not None:
            audio.terminate()
        signal.signal(signal.SIGINT, previous_sigint_handler)


if __name__ == "__main__":
    listen_for_wake_word()
