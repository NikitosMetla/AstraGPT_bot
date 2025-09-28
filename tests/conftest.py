"""
Конфигурация pytest для Playwright тестов
"""
import pytest
from playwright.sync_api import sync_playwright, Browser, BrowserContext


@pytest.fixture(scope="session")
def browser():
    """Создает браузер для всех тестов"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,  # Установите False для видимого браузера
            slow_mo=1000   # Замедление для отладки
        )
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def context(browser: Browser):
    """Создает контекст браузера для каждого теста"""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    yield context
    context.close()


@pytest.fixture(scope="function")
def page(context: BrowserContext):
    """Создает новую страницу для каждого теста"""
    page = context.new_page()
    
    # Устанавливаем таймауты
    page.set_default_timeout(10000)
    page.set_default_navigation_timeout(15000)
    
    yield page
    page.close()


# Хуки для скриншотов при ошибках
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Создает скриншот при ошибке теста"""
    outcome = yield
    rep = outcome.get_result()
    
    if rep.when == "call" and rep.failed:
        # Получаем страницу из фикстуры
        if "page" in item.fixturenames:
            page = item.funcargs["page"]
            screenshot_path = f"tests/screenshots/{item.name}_failure.png"
            page.screenshot(path=screenshot_path)
            print(f"Screenshot saved: {screenshot_path}")
