import pyautogui
import time
import re
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

def send_whatsapp_message(text):
    """
    Expects phrasing like: 'message sweety to wake up at 5am tomorrow'
    Handles speech-to-text quirks where 'to' may be transcribed as '2' or 'too',
    or the user naturally says 'that' instead.
    """
    try:
        after_message = text.split("message", 1)[1].strip()
        # Split on the first occurrence of to / 2 / too / that (as a whole word)
        parts = re.split(r'\s+(?:to|2|too|that)\s+', after_message, maxsplit=1)
        if len(parts) != 2:
            return "Couldn't understand that. Try: message [name] to [your text]"
        contact, message = parts[0].strip(), parts[1].strip()
    except IndexError:
        return "Couldn't understand that. Try: message [name] to [your text]"

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