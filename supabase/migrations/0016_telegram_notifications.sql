-- Трекинг уведомлений в Telegram-чат админов: какому событию (заявка на
-- проверку, блок-пост, новое сообщение в чате) какое сообщение бота в
-- Telegram соответствует — чтобы при разрешении события бот мог удалить
-- своё же сообщение и не захламлять чат неактуальными уведомлениями.
-- См. backend/telegram_notify.py.

create table telegram_notifications (
    id uuid primary key default gen_random_uuid(),
    kind text not null check (kind in ('review', 'block_post', 'chat')),
    -- Стабильный ключ события в рамках kind: review.id / "team_id:character_id"
    -- для блок-поста / chat.id — ровно то же самое, чем это событие уже
    -- идентифицируется в остальном коде (list_pending_block_posts и т.п.).
    event_key text not null,
    telegram_message_id bigint not null,
    created_at timestamptz not null default now(),
    unique (kind, event_key)
);

alter table telegram_notifications enable row level security;

-- Только backend (service_role) читает/пишет эту таблицу — никакого доступа
-- с фронтенда команде или админке не нужно, поэтому select/insert-политик
-- сознательно нет (тот же подход, что у call_phases/phone_numbers).
