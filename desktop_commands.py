import pyautogui
import time
import subprocess
from pywinauto import Desktop

def _focus_whatsapp():
    """Bring an already-open WhatsApp window to the front. Returns True if found."""
    try:
        windows = Desktop(backend="uia").windows(title_re=".*WhatsApp.*")
        if windows:
            windows[0].set_focus()
            return True
    except Exception:
        pass
    return False

def open_whatsapp(text=""):
    if _focus_whatsapp():
        return "WhatsApp is already open"

    # Launch via Windows Start Search — works regardless of how it was installed
    pyautogui.press('win')
    time.sleep(1)
    pyautogui.typewrite('whatsapp', interval=0.05)
    time.sleep(1)
    pyautogui.press('enter')
    time.sleep(4)  # give the app time to fully load
    return "Opening WhatsApp"

def send_whatsapp_message_to(contact, message):
    """Search for a WhatsApp contact and send them a message."""
    if not contact or not message:
        return "Please provide both a contact and a message."

    if not _focus_whatsapp():
        open_whatsapp()
        time.sleep(2)

    time.sleep(1)
    pyautogui.hotkey('ctrl', 'f')      # open chat search
    time.sleep(0.5)
    pyautogui.typewrite(contact, interval=0.05)
    time.sleep(1.5)
    pyautogui.press('down')           # highlight first search result
    pyautogui.press('enter')          # open that chat
    time.sleep(1)

    pyautogui.typewrite(message, interval=0.03)
    time.sleep(0.3)
    pyautogui.press('enter')          # send

    return f"Message sent to {contact}"


def launch_whatsapp(text=""):
    """Launch WhatsApp Desktop through its registered Windows protocol."""
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "whatsapp:"], shell=False)
        return "Opening WhatsApp"
    except OSError as error:
        return f"Couldn't launch WhatsApp: {error}"


def open_app(app_path):
    """Launch a desktop application from its executable path."""
    app_path = app_path.strip().strip('"')
    if not app_path:
        return "Please provide an application path."

    try:
        subprocess.Popen([app_path], shell=False)
        return f"Opening {app_path}"
    except OSError as error:
        return f"Couldn't open {app_path}: {error}"
