from browser_driver import get_driver, quit_driver, set_browser
import time
import re

from desktop_commands import (
    launch_whatsapp,
    open_app,
    send_whatsapp_message_to,
)
from app_launcher import launch_app, resolve_app
import youtube_controller
import modes


def open_site(text):
    if "google" in text:
        url = "https://www.google.com"
    elif "youtube" in text:
        url = "https://www.youtube.com"
    else:
        url = "https://www." + text.split("open")[-1].strip().replace(" ", "") + ".com"
    try:
        get_driver().get(url)
        return f"Opening {url}"
    except Exception:
        return "I couldn't open that site right now."


def _clean_youtube_query(query):
    """Remove filler words like 'on youtube', 'youtube', 'for' from a spoken query."""
    query = re.sub(r"\b(on|in)\s+youtube\b", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^\s*(for\s+)?(youtube\s*)?(for\s+)?", "", query, flags=re.IGNORECASE)
    return query.strip()


def search_youtube(text):
    """
    Expects phrasing like: 'open youtube and search cooking videos'
    or just 'search cooking videos on youtube'
    """
    try:
        query = text.split("search", 1)[1].strip()
    except IndexError:
        return "What do you want to search for?"

    query = _clean_youtube_query(query)

    if not query:
        return "What do you want to search for?"

    return youtube_controller.search(query)


def play_video(text):
    query = re.sub(r"^play\s+", "", text).strip()
    query = re.sub(r"\b(on|in)\s+youtube\b", "", query).strip()
    if query in {"", "a video", "any video", "video", "any"}:
        return youtube_controller.play_index(0)
    ordinals = {"first": 0, "second": 1, "third": 2, "1st": 0, "2nd": 1, "3rd": 2, "number 1": 0, "number 2": 1, "number 3": 2, "video 1": 0, "video 2": 1, "video 3": 2}
    if any(re.fullmatch(rf"(?:the )?{re.escape(word)} video", query) for word in ordinals):
        return youtube_controller.play_index(next(value for word, value in ordinals.items() if word in query), True)
    return youtube_controller.play_title(query)


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


def message_whatsapp_from_text(text):
    """Parse 'message [contact] saying [text]' or 'message [contact] to [text]'."""
    match = re.match(
        r"^\s*message\s+(.+?)\s+(?:saying|to|2|too|that)\s+(.+?)\s*$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return "Couldn't understand that. Try: message [contact] saying [text]"

    contact, message = match.groups()
    return send_whatsapp_message_to(contact.strip(), message.strip())


def open_app_from_text(text):
    explicit_app = bool(re.match(r"^(?:open|launch|start)\s+app\s+", text, flags=re.I))
    name = re.sub(r"^(?:open|launch|start)\s+(?:app\s+)?", "", text, flags=re.I).strip()
    if "\\" in name or name.lower().endswith(".exe"):
        return open_app(name)
    if resolve_app(name):
        return launch_app(name)
    if explicit_app:
        return "Command not recognized"
    return open_site("open " + name)


def is_shutdown_command(text):
    return re.sub(r"\s+", " ", text.strip().lower()) in {"stop", "exit", "quit", "shutdown", "shut down", "goodbye", "stop listening"}

def _normalize(text):
    text = re.sub(r"^\s*(?:alexa|jarvis)\b[,.\s]*", "", text.lower())
    text = re.sub(r"^\s*(?:please\s+|can you\s+)", "", text)
    return re.sub(r"\byt\b|\byou tube\b|\bnote pad\b", lambda m: "youtube" if m.group(0) in {"yt", "you tube"} else "notepad", text).strip()

# Anchored regex routes prevent incidental words such as "display" and "research"
# from triggering play/search handlers.
ROUTES = [
    (r"^pause\s+(?:the\s+)?video$", lambda text: youtube_controller.control("pause")),
    (r"^resume\s+(?:the\s+)?video$", lambda text: youtube_controller.control("resume")),
    (r"^stop\s+(?:the\s+)?video$", lambda text: youtube_controller.control("stop")),
    (r"^message\b", message_whatsapp_from_text),
    (r"^(?:open|launch)\s+whatsapp$", launch_whatsapp),
    (r"^search\b", search_youtube),
    (r"^play\b", play_video),
    (r"^(?:open|launch|start)\b", open_app_from_text),
    (r"^scroll\s+down$", scroll_down),
    (r"^scroll\s+up$", scroll_up),
    (r"^screenshot$", take_screenshot),
    (r"^close\s+browser$", close_browser),
]

def _execute_single(text):
    """Route one normalized command; compound execution deliberately reuses this."""
    if modes.is_mode_command(text):
        return modes.handle_command(text)
    for pattern, handler in ROUTES:
        if re.search(pattern, text):
            return handler(text)
    return "Command not recognized"


def _route_verbs():
    """Read leading verbs from ROUTES so additions naturally become chainable."""
    verbs = set()
    for pattern, _handler in ROUTES:
        grouped = re.match(r"^\^\(\?:([a-z|]+)\)", pattern)
        literal = re.match(r"^\^([a-z]+)", pattern)
        if grouped:
            verbs.update(grouped.group(1).split("|"))
        elif literal:
            verbs.add(literal.group(1))
    return verbs


def _split_commands(text):
    """Split only at connectors that introduce another known command."""
    if re.match(r"^message\b", text):
        return [text]  # Message bodies are free-form and must remain untouched.

    verbs = "|".join(sorted(_route_verbs(), key=len, reverse=True))
    connector = rf"\s+(?:(?:and then|after that|then)|and)\s+(?=(?:{verbs})\b)"
    steps = [part.strip() for part in re.split(connector, text) if part.strip()]

    # Voice recognition often omits the connector in this common YouTube request.
    if len(steps) == 1:
        implicit = re.match(
            r"^(search\s+.+?)\s+(play\s+(?:(?:the\s+)?(?:first|second|third|[123](?:st|nd|rd)?|number\s+[123])\s+video|(?:a|any)\s+video|video\s+[123]))$",
            text,
        )
        if implicit:
            steps = [implicit.group(1), implicit.group(2)]
    return steps


def _reply_ok(reply):
    failure_markers = (
        "couldn't", "command not recognized", "don't know", "not installed",
        "i found only", "please search", "what do you want", "needs consent",
        "didn't open a results page",
    )
    return not any(marker in reply.lower() for marker in failure_markers)


def _opens_or_launches(step):
    return bool(re.match(r"^(?:open|launch|start|search)\b", step))


def _browser_choice(step):
    """Return Selenium's browser name for an explicit Edge/Chrome app command."""
    if not re.match(r"^(?:open|launch|start)\b", step):
        return None
    name = re.sub(r"^(?:open|launch|start)\s+(?:app\s+)?", "", step).strip()
    entry = resolve_app(name)
    if entry and entry.name == "Microsoft Edge":
        return "edge", entry.name
    if entry and entry.name == "Google Chrome":
        return "chrome", entry.name
    return None


def _needs_browser(step):
    return bool(re.match(r"^(?:search|play|pause|resume|stop|scroll|screenshot)\b", step)) or (
        bool(re.match(r"^(?:open|launch|start)\b", step)) and _browser_choice(step) is None
    )


def execute_command(text):
    text = _normalize(text)
    if not text:
        return "I'm listening. Say a command after the wake word."
    steps = _split_commands(text)
    if len(steps) > 5:
        return "I can run up to 5 commands at a time."

    replies = []
    for number, step in enumerate(steps, start=1):
        choice = _browser_choice(step)
        uses_browser_later = any(_needs_browser(later) for later in steps[number:])
        if choice and uses_browser_later:
            browser_name, display_name = choice
            try:
                set_browser(browser_name)
                reply = f"Opening {display_name}."
            except Exception:
                reply = f"I couldn't start {display_name}."
        else:
            reply = _execute_single(step)
        replies.append(reply.rstrip("."))
        if not _reply_ok(reply):
            if len(steps) == 1:
                return reply
            return ". ".join(replies) + f". Step {number} failed."
        if number < len(steps) and _opens_or_launches(step):
            time.sleep(1.5)
    return ". ".join(replies)
