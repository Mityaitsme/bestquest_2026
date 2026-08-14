"""Уведомления в Telegram-чат админов о новых событиях, требующих внимания
оператора/актёра: заявка на проверку, блок-пост, новое сообщение команды в
чате (техподдержка или диалог с персонажем в режиме operator — сценарные
диалоги и GPT-режим оператора не отвлекают).

Каждое событие — одно сообщение от бота; когда событие разрешается (заявка
принята/отклонена, блок-пост отвечен, оператор ответил в чате), бот удаляет
своё же сообщение, чтобы в чате оставались только реально висящие дела —
если сообщений много, это сигнал, что ответственные не справляются.

Асинхронно: вся работа (проверка дублей в БД + запрос к Telegram + запись
id сообщения) выполняется в отдельном потоке — публичные notify_*/*_resolved
функции только планируют эту работу и сразу возвращаются. Раньше запрос к
Telegram выполнялся синхронно прямо внутри обработки HTTP-запроса команды/
оператора — с таймаутом в REQUEST_TIMEOUT_SECONDS это означало, что
отправка сообщения командой могла реально ждать до этого таймаута, если
сеть до api.telegram.org была медленной или недоступна. TELEGRAM_BOT_TOKEN/
TELEGRAM_CHAT_ID могут быть не настроены (тогда всё тихо no-op, с логом) —
это никогда не должно ронять основное действие команды/оператора.

Логи (print, видно в консоли Flask-процесса) на каждом шаге — специально,
чтобы можно было быстро понять, почему уведомление не пришло: не настроен
конфиг / уже есть висящее уведомление (дубль не шлём) / сбой запроса к
Telegram / успешная отправка или удаление.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from config import load_config
from supabase_client import get_supabase_client

API_URL = "https://api.telegram.org/bot{token}/{method}"
REQUEST_TIMEOUT_SECONDS = 5
# Москва не переходит на летнее время с 2014 года - фиксированный сдвиг
# проще и надёжнее, чем zoneinfo (на Windows требует отдельного пакета tzdata).
MOSCOW_TZ = timezone(timedelta(hours=3))


def _now_hhmm() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%H:%M")


def _log(message: str) -> None:
    # flush=True обязателен: это фоновый поток, а stdout при перенаправлении
    # в файл (не в интерактивный терминал) буферизуется блоками — без flush
    # строки могли зависать в буфере минутами, вместо того чтобы сразу быть
    # видны в консоли/логах Render.
    print(f"[telegram_notify] {message}", flush=True)


def _run_async(fn, *args) -> None:
    """Запустить fn(*args) в отдельном потоке и сразу вернуться — вызывающий
    HTTP-запрос не должен ждать ответа от Telegram."""
    threading.Thread(target=_safe_run, args=(fn, *args), daemon=True).start()


def _safe_run(fn, *args) -> None:
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 — фоновый поток, ронять нечего, только логируем
        _log(f"фоновая задача упала: {exc}")


def _call(method: str, payload: dict, token: str) -> dict | None:
    url = API_URL.format(token=token, method=method)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        _log(f"запрос {method} не удался: {exc}")
        return None

    if not result.get("ok"):
        _log(f"{method} вернул ok=false: {result}")
    return result


def _notify(kind: str, event_key: str, text: str) -> None:
    """Отправить сообщение и запомнить его id — но только если по этому
    (kind, event_key) ещё нет висящего уведомления (чтобы несколько
    сообщений команды подряд в один и тот же чат не плодили дубликаты)."""
    config = load_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        _log(
            f"TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не настроены "
            f"(проверьте .env и что процесс перезапущен после его правки) — "
            f"пропускаю: {kind}:{event_key}"
        )
        return

    client = get_supabase_client()
    existing = (
        client.table("telegram_notifications")
        .select("id")
        .eq("kind", kind)
        .eq("event_key", event_key)
        .execute()
        .data
    )
    if existing:
        _log(f"уведомление уже висит, не дублирую: {kind}:{event_key}")
        return

    result = _call(
        "sendMessage",
        {"chat_id": config.telegram_chat_id, "text": text},
        config.telegram_bot_token,
    )
    if not result or not result.get("ok"):
        _log(f"отправка не удалась: {kind}:{event_key}")
        return

    message_id = result["result"]["message_id"]
    try:
        client.table("telegram_notifications").insert(
            {"kind": kind, "event_key": event_key, "telegram_message_id": message_id}
        ).execute()
    except Exception as exc:  # noqa: BLE001 — граница с внешним сервисом, не роняем вызывающий код
        _log(f"не удалось сохранить запись отслеживания: {exc}")
        return

    _log(f"отправлено: {kind}:{event_key} (message_id={message_id})")


def _resolve(kind: str, event_key: str) -> None:
    """Удалить уведомление(-я) для этого события, если есть."""
    config = load_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return

    client = get_supabase_client()
    rows = (
        client.table("telegram_notifications")
        .select("id, telegram_message_id")
        .eq("kind", kind)
        .eq("event_key", event_key)
        .execute()
        .data
    )
    if not rows:
        return

    for row in rows:
        _call(
            "deleteMessage",
            {"chat_id": config.telegram_chat_id, "message_id": row["telegram_message_id"]},
            config.telegram_bot_token,
        )
        client.table("telegram_notifications").delete().eq("id", row["id"]).execute()
        _log(f"удалено: {kind}:{event_key} (message_id={row['telegram_message_id']})")


def _check_and_notify_block_post(team_id: str, character_id: str, node_id: str | None) -> None:
    if not node_id:
        return
    client = get_supabase_client()
    node = client.table("dialogue_nodes").select("is_block_post").eq("id", node_id).execute().data
    if not node or not node[0]["is_block_post"]:
        return

    team = client.table("teams").select("name").eq("id", team_id).execute().data
    character = client.table("characters").select("name").eq("id", character_id).execute().data
    _notify(
        "block_post",
        f"{team_id}:{character_id}",
        f"{_now_hhmm()}: Блок-пост ждёт ответа — команда «{team[0]['name'] if team else '?'}», "
        f"персонаж «{character[0]['name'] if character else '?'}»",
    )


# ---- Публичные функции по каждому виду события — каждая только планирует
# работу в фоне и сразу возвращается, ничего не блокирует ----


def notify_review_submitted(review_id: str, team_name: str, stage_title: str) -> None:
    _run_async(
        _notify,
        "review",
        review_id,
        f"{_now_hhmm()}: Новая заявка на проверку от команды «{team_name}»! "
        f"Задание: «{stage_title}»",
    )


def notify_review_resolved(review_id: str) -> None:
    _run_async(_resolve, "review", review_id)


def notify_block_post_created(
    team_id: str, character_id: str, team_name: str, character_name: str
) -> None:
    _run_async(
        _notify,
        "block_post",
        f"{team_id}:{character_id}",
        f"{_now_hhmm()}: Блок-пост ждёт ответа — команда «{team_name}», "
        f"персонаж «{character_name}»",
    )


def notify_block_post_resolved(team_id: str, character_id: str) -> None:
    _run_async(_resolve, "block_post", f"{team_id}:{character_id}")


def notify_if_block_post(team_id: str, character_id: str, node_id: str | None) -> None:
    """Общая проверка для мест, где диалог может "приземлиться" на
    блок-пост (обычный переход по next_node_id и телепорт через
    resumes_dialogue_at) — если узел блок-постовый, шлёт уведомление.
    Сама проверка (запрос к dialogue_nodes) тоже уходит в фон, чтобы не
    добавлять задержку в choose_option/resolve_block_post/jump_to_node."""
    _run_async(_check_and_notify_block_post, team_id, character_id, node_id)


def notify_chat_message(
    chat_id: str, team_name: str, chat_type: str, character_name: str | None
) -> None:
    if chat_type == "support":
        label = "в техподдержку"
    else:
        label = f"в диалоге с «{character_name}»" if character_name else "в диалоге"
    _run_async(
        _notify,
        "chat",
        chat_id,
        f"{_now_hhmm()}: Новое сообщение {label} от команды «{team_name}»!",
    )


def notify_chat_resolved(chat_id: str) -> None:
    _run_async(_resolve, "chat", chat_id)
