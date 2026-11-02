"""Selenium-only YouTube search and playback state for this assistant session."""
from dataclasses import dataclass, field
import re
import time
from urllib.parse import parse_qs, quote, urlparse
from browser_driver import get_driver

@dataclass
class YouTubeSession:
    query: str = ""
    results: list[tuple[str, str]] = field(default_factory=list)
session = YouTubeSession()
RESULT_WAIT_SECONDS = 20
PLAYBACK_WAIT_SECONDS = 15

_LINK_SCAN_SCRIPT = """
return Array.from(document.querySelectorAll('a[href*="/watch?v="]'))
  .filter(a => !a.href.includes('/shorts/'))
  .map(a => ({href: a.href, title: a.getAttribute('title') || a.getAttribute('aria-label') || a.innerText || a.textContent || ''}));
"""

def _videos(driver):
    found, ids = [], set()
    for link in driver.find_elements("css selector", "a[href*='/watch?v=']"):
        href = link.get_attribute("href") or ""
        video_id = parse_qs(urlparse(href).query).get("v", [None])[0]
        title = (link.get_attribute("title") or link.text or "").strip()
        if video_id and title and video_id not in ids:
            ids.add(video_id); found.append((title, f"https://www.youtube.com/watch?v={video_id}"))
            if len(found) == 10: break
    return found


def _results_from_links(links):
    found, ids = [], set()
    for link in links or []:
        href = link.get("href", "") if isinstance(link, dict) else ""
        title = (link.get("title", "") if isinstance(link, dict) else "").strip()
        video_id = parse_qs(urlparse(href).query).get("v", [None])[0]
        if "/shorts/" not in href and video_id and title and video_id not in ids:
            ids.add(video_id)
            found.append((title, f"https://www.youtube.com/watch?v={video_id}"))
            if len(found) == 10:
                break
    return found


def _fallback_results(driver):
    ids = re.findall(r'"videoId":"([\w-]{11})"', getattr(driver, "page_source", ""))
    found, seen = [], set()
    for video_id in ids:
        if video_id not in seen:
            seen.add(video_id)
            found.append((f"video {len(found) + 1}", f"https://www.youtube.com/watch?v={video_id}"))
            if len(found) == 10:
                break
    return found


def _collect_results(driver):
    """Poll the rendered page with one DOM scan per attempt, then use source fallback."""
    deadline = time.monotonic() + RESULT_WAIT_SECONDS
    dom_count = 0
    while True:
        links = driver.execute_script(_LINK_SCAN_SCRIPT)
        dom_count = len(links or [])
        results = _results_from_links(links)
        if results or time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    fallback = _fallback_results(driver) if not results else []
    return results or fallback, dom_count, len(fallback)


def _is_consent_page(driver):
    details = " ".join((getattr(driver, "current_url", ""), getattr(driver, "title", ""), getattr(driver, "page_source", "")[:2000])).lower()
    return "before you continue" in details or "consent.youtube.com" in details


def _is_results_page(driver):
    parsed = urlparse(getattr(driver, "current_url", ""))
    return parsed.hostname and parsed.hostname.endswith("youtube.com") and parsed.path == "/results"

def search(query):
    query = query.strip()
    if not query: return "What do you want to search for?"
    try:
        driver = get_driver()
        search_url = f"https://www.youtube.com/results?search_query={quote(query)}"
        driver.get(search_url)
        driver.execute_script("window.scrollBy(0, 400);")
        driver.execute_script("window.scrollBy(0, -400);")
        results, dom_count, fallback_count = _collect_results(driver)
        if not results:
            driver.get(search_url)  # one retry after a fresh results-page load
            driver.execute_script("window.scrollBy(0, 400);")
            driver.execute_script("window.scrollBy(0, -400);")
            results, dom_count, fallback_count = _collect_results(driver)
        print(f"[yt] url: {getattr(driver, 'current_url', '')}")
        print(f"[yt] title: {getattr(driver, 'title', '')}")
        print(f"[yt] links: dom={dom_count} fallback={fallback_count}")
        session.query, session.results = query, results
    except Exception: return "I couldn't search YouTube right now."
    if _is_consent_page(driver):
        return "YouTube needs consent before I can search."
    if not _is_results_page(driver):
        return "YouTube didn't open a results page."
    return f"I couldn't find any YouTube results for {query}." if not session.results else f"Searching YouTube for {query}"

_PLAYER = "document.querySelector('video.html5-main-video') || document.querySelector('video')"
_VIDEO_STATE_SCRIPT = f"const v={_PLAYER}; const p=document.querySelector('#movie_player'); return v ? {{exists:true, paused:v.paused, ended:v.ended, currentTime:v.currentTime, readyState:v.readyState, adShowing:!!(p && p.classList.contains('ad-showing'))}} : {{exists:false}};"


def _video_state(driver):
    state = driver.execute_script(_VIDEO_STATE_SCRIPT) or {"exists": False}
    print("[yt] poll: paused={paused} ended={ended} currentTime={currentTime} readyState={readyState}".format(
        paused=state.get("paused"), ended=state.get("ended"), currentTime=state.get("currentTime"), readyState=state.get("readyState")
    ))
    return state


def _confirm_playing(driver):
    first = _video_state(driver)
    if not first.get("exists") or first.get("paused") or first.get("ended") or first.get("readyState", 0) < 2:
        return False, first
    time.sleep(1.5)
    second = _video_state(driver)
    playing = (not second.get("paused") and not second.get("ended") and second.get("readyState", 0) >= 2
               and second.get("currentTime", 0) - first.get("currentTime", 0) >= 0.5)
    return playing, second


def _wait_for_ready_video(driver):
    deadline = time.monotonic() + PLAYBACK_WAIT_SECONDS
    while True:
        state = _video_state(driver)
        if state.get("exists") and state.get("readyState", 0) >= 2:
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(0.5)


def _escalate_playback(driver, step):
    print(f"[yt] escalation: {step}")
    if step == "play":
        return driver.execute_script(f"const v={_PLAYER}; if (!v) return false; try {{ const p=v.play(); if (p) p.catch(()=>{{}}); return true; }} catch (e) {{ return false; }}")
    if step == "play button":
        return driver.execute_script("const b=document.querySelector('button.ytp-play-button'); if (!b) return false; b.click(); return true;")
    if step == "large play button":
        return driver.execute_script("const b=document.querySelector('button.ytp-large-play-button'); if (!b) return false; b.click(); return true;")
    if step == "video click":
        return driver.execute_script(f"const v={_PLAYER}; if (!v) return false; v.click(); return true;")
    body = driver.find_element("tag name", "body")
    body.send_keys("k")
    return True


def _is_watch_page(driver):
    parsed = urlparse(getattr(driver, "current_url", ""))
    return parsed.hostname and parsed.hostname.endswith("youtube.com") and parsed.path == "/watch"


def _start(result):
    title, url = result
    try:
        driver = get_driver()
        current_url = getattr(driver, "current_url", "")
        current_id = parse_qs(urlparse(current_url).query).get("v", [None])[0]
        requested_id = parse_qs(urlparse(url).query).get("v", [None])[0]
        if current_id != requested_id:
            driver.get(url)
        print(f"[yt] watch url: {getattr(driver, 'current_url', '')}")
        if _is_consent_page(driver):
            return "YouTube needs consent before I can play videos."
        if not _is_watch_page(driver):
            return "YouTube didn't open a video page."
        _wait_for_ready_video(driver)
        playing, state = _confirm_playing(driver)
        if not playing:
            for step in ("play", "play button", "large play button", "video click", "keyboard k"):
                _escalate_playback(driver, step)
                playing, state = _confirm_playing(driver)
                if playing:
                    break
    except Exception:
        print("[yt] final verdict: playback error")
        return f"I opened {title} but couldn't confirm it started."
    if playing:
        print("[yt] final verdict: playing")
        ad_note = " (an ad is playing first)" if state.get("adShowing") else ""
        return f"Playing {title}.{ad_note}"
    print("[yt] final verdict: not playing")
    return f"I opened {title} but couldn't confirm it started."

def play_index(index, require_search=False):
    if not session.results:
        if require_search: return "Please search YouTube first."
        try:
            driver = get_driver(); driver.get("https://www.youtube.com/"); results = _videos(driver)
        except Exception: return "I couldn't open YouTube right now."
        if not results: return "I couldn't find a video to play."
        return _start(results[0])
    if index >= len(session.results): return f"I found only {len(session.results)} results."
    return _start(session.results[index])

def play_title(title):
    words = set(re.findall(r"\w+", title.lower()))
    if session.results:
        ranked = [(len(words & set(re.findall(r"\w+", name.lower()))), (name, url)) for name, url in session.results]
        score, result = max(ranked, key=lambda pair: pair[0])
        if score: return _start(result)
    reply = search(title)
    return reply if not session.results else _start(session.results[0])

def control(action):
    scripts = {
        "pause": f"const v={_PLAYER}; if (!v) return {{ok:false}}; const before=v.currentTime; v.pause(); const after=v.currentTime; return {{ok:v.paused && Math.abs(after-before)<0.05, time:after}};",
        "stop": f"const v={_PLAYER}; if (!v) return {{ok:false}}; const before=v.currentTime; v.pause(); const after=v.currentTime; return {{ok:v.paused && Math.abs(after-before)<0.05, time:after}};",
        "resume": f"const v={_PLAYER}; if (!v) return {{ok:false}}; v.play(); return {{ok:!v.paused}};",
    }
    try: result = get_driver().execute_script(scripts[action])
    except Exception: return "I couldn't control the video."
    ok = result.get("ok", False) if isinstance(result, dict) else bool(result)
    if not ok:
        return "I couldn't verify the video control."
    if action == "resume":
        return "Resuming."
    position = result.get("time") if isinstance(result, dict) else None
    if isinstance(position, (int, float)):
        minutes, seconds = divmod(int(position), 60)
        verb = "Paused" if action == "pause" else "Stopped"
        return f"{verb} at {minutes} minutes {seconds} seconds."
    return "Paused." if action == "pause" else "Stopped."
