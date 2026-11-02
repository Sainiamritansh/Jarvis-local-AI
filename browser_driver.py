from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

driver = None
preferred_browser = "chrome"


def _browser_options(browser):
    options = webdriver.EdgeOptions() if browser == "edge" else webdriver.ChromeOptions()
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    return options


def set_browser(browser):
    """Select the Selenium browser for this session and start it if needed."""
    global preferred_browser
    if browser not in {"chrome", "edge"}:
        raise ValueError("Unsupported browser")
    if browser != preferred_browser:
        quit_driver()
        preferred_browser = browser
    return get_driver()

def get_driver():
    """Returns a shared WebDriver instance. Recreates it if the browser was closed."""
    global driver
    if driver is not None:
        try:
            _ = driver.title  # simple check: does the session still respond?
        except (InvalidSessionIdException, WebDriverException):
            driver = None  # session is dead, force a fresh one

    if driver is None:
        if preferred_browser == "edge":
            driver = webdriver.Edge(options=_browser_options("edge"))
        else:
            driver = webdriver.Chrome(options=_browser_options("chrome"))
        driver.maximize_window()

    return driver

def quit_driver():
    global driver
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
        driver = None
