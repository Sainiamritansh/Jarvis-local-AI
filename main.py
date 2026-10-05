import keyboard
from voice_engine import speak, listen
from commands import execute_command

def run():
    speak("Systems online. Press space to give a command.")

    while True:
        keyboard.wait('space')
        speak("Listening")
        text = listen()

        if not text:
            continue

        if "exit" in text or "shutdown" in text:
            speak("Shutting down. Goodbye.")
            break

        result = execute_command(text)
        speak(result)

if __name__ == "__main__":
    run()