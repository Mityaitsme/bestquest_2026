-- Базовые сущности для авторизации и графа задач (MVP).
-- Решения зафиксированы в docs/database.md и docs/requirements.md:
--   - логин общий на команду (без отдельной сущности "пользователь");
--   - роли админов: только actor / operator, без superadmin;
--   - граф задач: только AND-логика предпосылок (все прямые
--     предшественники этапа должны быть завершены).
--
-- Более сложные сущности (поля ответа, ручная проверка, чаты, звонки,
-- персонажи) сюда намеренно не входят — добавятся отдельными миграциями
-- на следующих этапах.

create extension if not exists pgcrypto;

create table teams (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    password_hash text not null,
    created_at timestamptz not null default now()
);

create table admins (
    id uuid primary key default gen_random_uuid(),
    username text not null unique,
    password_hash text not null,
    role text not null check (role in ('actor', 'operator')),
    created_at timestamptz not null default now()
);

create table stages (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    title text not null,
    description text not null default '',
    created_at timestamptz not null default now()
);

-- Рёбра графа задач: to_stage_id становится доступен, когда завершены
-- ВСЕ этапы, являющиеся его from_stage_id (только AND, без "хотя бы один из").
create table stage_edges (
    from_stage_id uuid not null references stages (id) on delete cascade,
    to_stage_id uuid not null references stages (id) on delete cascade,
    primary key (from_stage_id, to_stage_id)
);

-- Текущее состояние команды по каждому этапу.
-- Начальные ("корневые") этапы получают статус 'available' при регистрации
-- команды — это делает бэкенд при создании команды, а не эта схема.
create table team_stage_progress (
    team_id uuid not null references teams (id) on delete cascade,
    stage_id uuid not null references stages (id) on delete cascade,
    status text not null default 'locked'
        check (status in ('locked', 'available', 'completed')),
    completed_at timestamptz,
    completed_by_admin_id uuid references admins (id) on delete set null,
    completion_method text
        check (completion_method in ('actor', 'answer', 'checkbox', 'manual_review')),
    primary key (team_id, stage_id)
);

-- RLS включаем на всех таблицах сразу (безопасный дефолт Supabase).
-- Политики пока не пишем: прямого доступа с фронтенда к этим таблицам ещё
-- нет, backend всегда ходит через service_role key, который RLS игнорирует.
-- Политики для команд/админов появятся на этапе аутентификации.
alter table teams enable row level security;
alter table admins enable row level security;
alter table stages enable row level security;
alter table stage_edges enable row level security;
alter table team_stage_progress enable row level security;
