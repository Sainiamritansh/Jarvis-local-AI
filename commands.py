from browser_driver import get_driver, quit_driver
from selenium.webdriver.common.by import By
import time
from urllib.parse import quote
from desktop_commands import open_whatsapp, send_whatsapp_message

def open_site(text):
    if "google" in text:
        url = "https://www.google.com"
    elif "youtube" in text:
        url = "https://www.youtube.com"
    else:
        url = "https://www." + text.split("open")[-1].strip().replace(" ", "") + ".com"
    driver = get_driver()
    driver.get(url)
    return f"Opening {url}"

def search_youtube(text):
    """
    Expects phrasing like: 'open youtube and search cooking videos'
    or just 'search cooking videos on youtube'
    """
    try:
        query = text.split("search", 1)[1].strip()
    except IndexError:
        return "What do you want to search for?"

    query = query.replace("on youtube", "").strip()

    if not query:
        return "What do you want to search for?"

    driver = get_driver()
    url = f"https://www.youtube.com/results?search_query={quote(query)}"
    driver.get(url)
    return f"Searching YouTube for {query}"

def scroll_down(text):
    driver = get_driver()
    driver.execute_script("window.scrollBy(0, 500);")
    return "Scrolled down"

def scroll_up(text):
    driver = get_driver()
    driver.execute_script("window.scrollBy(0, -500);")
    return "Scrolled up"

def take_screenshot(text):
    driver = get_driver()
    filename = f"screenshot_{int(time.time())}.png"
    driver.save_screenshot(filename)
    return f"Screenshot saved as {filename}"

def close_browser(text):
    quit_driver()
    return "Closing browser"

# Map trigger phrases to functions.
# Order matters — first match wins, so put more specific phrases first.
COMMAND_MAP = [
    ("message", send_whatsapp_message),
    ("open whatsapp", open_whatsapp),
    ("search", search_youtube),
    ("open", open_site),
    ("scroll down", scroll_down),
    ("scroll up", scroll_up),
    ("screenshot", take_screenshot),
    ("close browser", close_browser),
]

def execute_command(text):
    for keyword, func in COMMAND_MAP:
        if keyword in text:
            return func(text)
    return "Command not recognized"