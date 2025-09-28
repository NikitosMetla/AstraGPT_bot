# Тестирование с Playwright

Этот каталог содержит Playwright тесты для проверки функциональности приложения.

## Установка зависимостей

```bash
pip install -r requirements-test.txt
playwright install chromium
```

## Запуск тестов

### Все тесты
```bash
pytest tests/ -v
```

### Конкретный тест
```bash
pytest tests/test_login_dashboard.py::test_login_and_dashboard_title -v
```

### С видимым браузером
```bash
pytest tests/ -v --headed
```

### Генерация HTML отчета
```bash
pytest tests/ -v --html=report.html --self-contained-html
```

## Структура тестов

- `conftest.py` - Конфигурация pytest и фикстуры
- `test_login_dashboard.py` - Тесты входа и дашборда
- `screenshots/` - Скриншоты при ошибках (создается автоматически)

## Тесты

### test_login_and_dashboard_title
- Проверяет успешный вход в систему
- Верифицирует заголовок дашборда
- Проверяет отсутствие формы входа на дашборде

### test_login_with_invalid_credentials
- Проверяет обработку неверных учетных данных
- Проверяет отображение сообщения об ошибке

### test_dashboard_navigation
- Проверяет основные элементы дашборда
- Тестирует навигацию

## Конфигурация

Настройки тестов находятся в:
- `pytest.ini` - Основная конфигурация pytest
- `conftest.py` - Фикстуры и хуки

## Отладка

При ошибках автоматически создаются скриншоты в папке `screenshots/`.

Для отладки можно запустить тесты с замедлением:
```bash
pytest tests/ -v --headed --slow-mo=1000
```
