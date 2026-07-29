-- Эмуляция звонков: набор номера, случайные ответы на "несуществующие"
-- номера, сюжетные номера с паролем и произвольным ветвлением фаз
-- (не обязательно бинарным — масштабируется на сколько угодно фаз).
--
-- "Несуществующие"/пранк-номера нигде не хранятся — это любой номер,
-- которого нет в phone_numbers; ответ на такой номер выбирается случайно
-- на уровне backend (см. backend/calls.py).

create table phone_numbers (
    id uuid primary key default gen_random_uuid(),
    number text not null unique,
    character_id uuid references characters (id) on delete set null
);

create table call_phases (
    id uuid primary key default gen_random_uuid(),
    phone_number_id uuid not null references phone_numbers (id) on delete cascade,
    -- content_key — стабильный ключ для контент-автора (см. import_content.py),
    -- на него ссылаются on_success/on_failure соседних фаз в YAML.
    content_key text not null,
    is_entry boolean not null default false,
    audio_url text not null,
    requires_password boolean not null default false,
    correct_password text,
    success_next_phase_id uuid references call_phases (id) on delete set null,
    failure_next_phase_id uuid references call_phases (id) on delete set null,
    unique (phone_number_id, content_key)
);

-- Ровно одна входная фаза на номер.
create unique index call_phases_one_entry_per_number on call_phases (phone_number_id) where is_entry;

create table call_logs (
    id uuid primary key default gen_random_uuid(),
    team_id uuid not null references teams (id) on delete cascade,
    dialed_number text,
    phone_number_id uuid references phone_numbers (id) on delete set null,
    outcome text not null check (outcome in ('nonexistent', 'unavailable', 'prank', 'story')),
    reached_phase_id uuid references call_phases (id) on delete set null,
    entered_password text,
    created_at timestamptz not null default now()
);

alter table phone_numbers enable row level security;
alter table call_phases enable row level security;
alter table call_logs enable row level security;

-- На phone_numbers/call_phases сознательно НЕТ select-политик даже для
-- authenticated: call_phases.correct_password не должен быть доступен
-- напрямую с фронтенда ни в каком виде — весь флоу звонка идёт только
-- через backend (service_role), который возвращает клиенту исключительно
-- безопасные поля (audio_url, requires_password), никогда сам пароль.

create policy "call_logs_select_own" on call_logs
    for select
    using (team_id = (select id from teams where auth_user_id = auth.uid()));
