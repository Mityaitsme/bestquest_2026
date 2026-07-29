-- Скриптованный диалог: узлы с вариантами ответа (1-4), ветвление,
-- "блок-посты" (нужно одобрение оператора, чтобы продвинуться) и
-- механика "скажите все варианты" (узел не отпускает команду, пока не
-- выбраны все опции по одной — выбор не влияет на сюжет, просто нужно
-- перебрать все).

create table dialogue_nodes (
    id uuid primary key default gen_random_uuid(),
    character_id uuid not null references characters (id) on delete cascade,
    content_key text not null,
    intro_message text not null default '',
    is_start boolean not null default false,
    -- Если true: next_node_id этого узла используется ТОЛЬКО когда команда
    -- выбрала ВСЕ варианты узла (по одному за раз); next_node_id самих
    -- вариантов в этом случае игнорируется.
    requires_all_options boolean not null default false,
    next_node_id uuid references dialogue_nodes (id) on delete set null,
    unique (character_id, content_key)
);

-- Ровно один стартовый узел на персонажа.
create unique index dialogue_nodes_one_start_per_character
    on dialogue_nodes (character_id) where is_start;

create table dialogue_options (
    id uuid primary key default gen_random_uuid(),
    node_id uuid not null references dialogue_nodes (id) on delete cascade,
    content_key text not null,
    option_text text not null,
    reply_message text not null,
    -- Используется, только если у родительского узла requires_all_options = false.
    next_node_id uuid references dialogue_nodes (id) on delete set null,
    requires_admin_approval boolean not null default false,
    unique (node_id, content_key)
);

-- Текущая позиция команды в диалоге с конкретным персонажем.
-- current_node_id = null означает "диалог ещё не начат или уже завершён".
create table team_dialogue_state (
    team_id uuid not null references teams (id) on delete cascade,
    character_id uuid not null references characters (id) on delete cascade,
    current_node_id uuid references dialogue_nodes (id) on delete set null,
    primary key (team_id, character_id)
);

-- Какие варианты в узлах с requires_all_options команда уже использовала.
create table team_dialogue_used_options (
    team_id uuid not null references teams (id) on delete cascade,
    option_id uuid not null references dialogue_options (id) on delete cascade,
    primary key (team_id, option_id)
);

-- Очередь "блок-постов": команда выбрала вариант с requires_admin_approval,
-- ответ уже показан, но позиция в диалоге сдвинется только когда оператор
-- нажмёт "да, всё норм".
create table dialogue_approvals (
    id uuid primary key default gen_random_uuid(),
    team_id uuid not null references teams (id) on delete cascade,
    option_id uuid not null references dialogue_options (id) on delete cascade,
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    reviewer_admin_id uuid references admins (id) on delete set null,
    created_at timestamptz not null default now(),
    reviewed_at timestamptz
);

alter table dialogue_nodes enable row level security;
alter table dialogue_options enable row level security;
alter table team_dialogue_state enable row level security;
alter table team_dialogue_used_options enable row level security;
alter table dialogue_approvals enable row level security;

-- Текст узлов/опций не секрет — команда должна их видеть, чтобы дальше
-- работал прямой Realtime, если понадобится фронтенду.
create policy "dialogue_nodes_select_authenticated" on dialogue_nodes
    for select
    using (auth.role() = 'authenticated');

create policy "dialogue_options_select_authenticated" on dialogue_options
    for select
    using (auth.role() = 'authenticated');

create policy "team_dialogue_state_select_own" on team_dialogue_state
    for select
    using (team_id = (select id from teams where auth_user_id = auth.uid()));
