PRESENT VPN — пакет /rules

Что добавляется:
- команда /rules;
- меню: соглашение, возвраты, конфиденциальность, тарифы;
- длинное соглашение автоматически делится на сообщения Telegram;
- ссылка на /rules в /help;
- уведомление о правилах перед выбором оплаты;
- тесты критического поведения.

База данных и платёжная логика не изменяются.

Применение:

1. Распакуйте архив в любое место вне проекта.
2. Откройте PowerShell в корне vpn_telegram_project.
3. Запустите:

C:\Users\User\PycharmProjects\pythonProject\.venv\Scripts\python.exe <ПУТЬ_К_ПАПКЕ>\apply_rules_patch.py

Скрипт:
- проверяет структуру проекта;
- меняет только нужные участки;
- создаёт резервную копию изменяемых файлов во временной папке Windows;
- не заменяет целиком app/bot/main.py, поэтому сохраняет текущие scheduler и production-изменения.

После применения:

C:\Users\User\PycharmProjects\pythonProject\.venv\Scripts\python.exe -m ruff check .
C:\Users\User\PycharmProjects\pythonProject\.venv\Scripts\python.exe -m pytest -q

Затем локально запустите бота и проверьте:
- /rules;
- каждую кнопку;
- /help;
- выбор тарифа перед оплатой.
