-- Базовая инфраструктура чата: персонажи, чаты команды, сообщения.
-- Скриптованный диалог (узлы/варианты/блок-посты) и интеграция с ChatGPT —
-- отдельные, более крупные куски на следующих этапах.

create table characters (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    nickname text not null unique,
    avatar_url text,
    public_lore text not null default ''
);

create table chats (
    id uuid primary key default gen_random_uuid(),
    team_id uuid not null references teams (id) on delete cascade,
    character_id uuid references characters (id) on delete cascade,
    chat_type text not null check (chat_type in ('character', 'support')),
    mode text not null default 'operator' check (mode in ('scripted', 'operator', 'gpt', 'muted')),
    created_at timestamptz not null default now(),
    unique (team_id, character_id)
);

-- unique(team_id, character_id) не ловит случай character_id IS NULL
-- (несколько NULL не считаются дубликатом) — отдельно гарантируем
-- ровно один чат техподдержки на команду.
create unique index chats_one_support_per_team on chats (team_id) where character_id is null;

create table messages (
    id uuid primary key default gen_random_uuid(),
    chat_id uuid not null references chats (id) on delete cascade,
    sender_type text not null check (sender_type in ('team', 'character', 'admin', 'system')),
    sender_admin_id uuid references admins (id) on delete set null,
    content text not null,
    message_kind text not null default 'normal' check (message_kind in ('normal', 'support_comment')),
    created_at timestamptz not null default now(),
    read_at timestamptz
);

alter table characters enable row level security;
alter table chats enable row level security;
alter table messages enable row level security;

-- Персонажи (имя/ник/лор) не секрет — видны любому вошедшему.
create policy "characters_select_authenticated" on characters
    for select
    using (auth.role() = 'authenticated');

create policy "chats_select_own" on chats
    for select
    using (team_id = (select id from teams where auth_user_id = auth.uid()));

create policy "messages_select_own" on messages
    for select
    using (
        chat_id in (
            select id from chats
            where team_id = (select id from teams where auth_user_id = auth.uid())
        )
    );
