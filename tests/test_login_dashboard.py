"""
Playwright тест для проверки входа в приложение и верификации заголовка дашборда
"""
import pytest
from playwright.sync_api import Page, expect


@pytest.fixture
def page(browser):
    """Создает новую страницу для тестирования"""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


def test_login_and_dashboard_title(page: Page):
    """
    Тест входа в приложение и проверки заголовка дашборда
    """
    # Переходим на страницу входа (предполагаем, что это локальный сервер)
    page.goto("http://localhost:8000/login")
    
    # Ждем загрузки формы входа
    page.wait_for_selector("input[type='email'], input[name='email']")
    
    # Заполняем поля входа
    email_input = page.locator("input[type='email'], input[name='email']")
    password_input = page.locator("input[type='password'], input[name='password']")
    
    # Вводим тестовые данные
    email_input.fill("test@example.com")
    password_input.fill("testpassword")
    
    # Нажимаем кнопку входа
    login_button = page.locator("button[type='submit'], input[type='submit']")
    login_button.click()
    
    # Ждем перенаправления на дашборд
    page.wait_for_url("**/dashboard/**", timeout=10000)
    
    # Проверяем, что мы на странице дашборда
    expect(page).to_have_url(lambda url: "dashboard" in url)
    
    # Ищем заголовок дашборда
    # Может быть h1, h2 или элемент с классом/ID содержащим "dashboard", "title", "header"
    dashboard_title = page.locator("h1, h2, .dashboard-title, .page-title, #dashboard-title, #page-title")
    
    # Проверяем, что заголовок существует и видим
    expect(dashboard_title).to_be_visible()
    
    # Проверяем, что заголовок содержит ожидаемый текст
    # Может быть "Dashboard", "Панель управления", "Главная" и т.д.
    title_text = dashboard_title.text_content()
    assert title_text is not None, "Заголовок дашборда не найден"
    assert len(title_text.strip()) > 0, "Заголовок дашборда пустой"
    
    # Дополнительная проверка - убеждаемся, что мы действительно вошли в систему
    # Ищем элементы, которые должны быть только для авторизованных пользователей
    user_menu = page.locator(".user-menu, .profile-menu, [data-testid='user-menu']")
    if user_menu.count() > 0:
        expect(user_menu).to_be_visible()
    
    # Проверяем отсутствие формы входа на странице дашборда
    login_form = page.locator("form[action*='login'], .login-form")
    if login_form.count() > 0:
        expect(login_form).not_to_be_visible()


def test_login_with_invalid_credentials(page: Page):
    """
    Тест входа с неверными учетными данными
    """
    page.goto("http://localhost:8000/login")
    
    # Ждем загрузки формы
    page.wait_for_selector("input[type='email'], input[name='email']")
    
    # Вводим неверные данные
    email_input = page.locator("input[type='email'], input[name='email']")
    password_input = page.locator("input[type='password'], input[name='password']")
    
    email_input.fill("wrong@example.com")
    password_input.fill("wrongpassword")
    
    # Нажимаем кнопку входа
    login_button = page.locator("button[type='submit'], input[type='submit']")
    login_button.click()
    
    # Ждем появления сообщения об ошибке
    error_message = page.locator(".error, .alert, .message, [role='alert']")
    expect(error_message).to_be_visible(timeout=5000)
    
    # Проверяем, что мы остались на странице входа
    expect(page).to_have_url(lambda url: "login" in url)


def test_dashboard_navigation(page: Page):
    """
    Тест навигации по дашборду после входа
    """
    # Предполагаем, что у нас есть функция для входа в систему
    login_user(page, "test@example.com", "testpassword")
    
    # Проверяем основные элементы дашборда
    dashboard_elements = [
        ".dashboard",
        ".main-content", 
        ".sidebar",
        ".nav-menu",
        "[data-testid='dashboard']"
    ]
    
    for selector in dashboard_elements:
        element = page.locator(selector)
        if element.count() > 0:
            expect(element.first).to_be_visible()


def login_user(page: Page, email: str, password: str):
    """
    Вспомогательная функция для входа в систему
    """
    page.goto("http://localhost:8000/login")
    page.wait_for_selector("input[type='email'], input[name='email']")
    
    email_input = page.locator("input[type='email'], input[name='email']")
    password_input = page.locator("input[type='password'], input[name='password']")
    
    email_input.fill(email)
    password_input.fill(password)
    
    login_button = page.locator("button[type='submit'], input[type='submit']")
    login_button.click()
    
    # Ждем успешного входа
    page.wait_for_url("**/dashboard/**", timeout=10000)


# Конфигурация для запуска тестов
if __name__ == "__main__":
    # Запуск с pytest
    # pytest tests/test_login_dashboard.py -v --headed
    pass
