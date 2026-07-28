"""Консольная утилита для создания админа (actor/operator).

Запуск (из папки backend, с активированным venv): python create_admin.py

Намеренно не HTTP-эндпоинт: управление аккаунтами админов делается
вручную, а не через публичный UI (см. docs/database.md).
"""

from __future__ import annotations

import getpass

from auth import ADMIN_ROLES, AuthError, register_admin


def main() -> None:
    username = input("Логин админа: ").strip()
    password = getpass.getpass("Пароль: ")

    role = ""
    while role not in ADMIN_ROLES:
        role = input(f"Роль ({'/'.join(ADMIN_ROLES)}): ").strip()

    try:
        admin_session = register_admin(username, password, role)
    except AuthError as exc:
        print(f"Ошибка: {exc}")
        return

    print(f"Готово: админ '{admin_session.username}' ({admin_session.role}) создан.")


if __name__ == "__main__":
    main()
