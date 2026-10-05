from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

driver = None

def get_driver():
    """Returns a shared WebDriver instance. Recreates it if the browser was closed."""
    global driver
    if driver is not None:
        try:
            _ = driver.title  # simple check: does the session still respond?
        except (InvalidSessionIdException, WebDriverException):
            driver = None  # session is dead, force a fresh one

    if driver is None:
        driver = webdriver.Chrome()
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