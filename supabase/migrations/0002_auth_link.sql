-- Связываем teams/admins с Supabase Auth (решение зафиксировано в чате:
-- аутентификация через Supabase Auth, а не свой логин на Flask).
--
-- Пароли теперь целиком хранятся и проверяются встроенным Supabase Auth
-- (auth.users), поэтому свой password_hash больше не нужен.
-- Вместо email у команды/админа используется синтетический адрес вида
-- "<uuid>@team.quest.local" — Supabase Auth требует email, а реального
-- email у команды нет; для входа используется человекочитаемое name/username,
-- backend сам подставляет auth_email при обращении к Supabase Auth.

alter table teams
    add column auth_user_id uuid not null unique references auth.users (id) on delete cascade,
    add column auth_email text not null unique,
    drop column password_hash;

alter table admins
    add column auth_user_id uuid not null unique references auth.users (id) on delete cascade,
    add column auth_email text not null unique,
    drop column password_hash;

-- Команда видит только свою собственную строку.
create policy "teams_select_own" on teams
    for select
    using (auth.uid() = auth_user_id);

-- Команда видит только свой прогресс по этапам.
create policy "team_stage_progress_select_own" on team_stage_progress
    for select
    using (team_id = (select id from teams where auth_user_id = auth.uid()));

-- Граф этапов (сами задачи и рёбра) не секрет — виден любому вошедшему
-- пользователю (команде или админу), нужен фронтенду для отрисовки графа.
create policy "stages_select_authenticated" on stages
    for select
    using (auth.role() = 'authenticated');

create policy "stage_edges_select_authenticated" on stage_edges
    for select
    using (auth.role() = 'authenticated');

-- Политики для admins и для доступа админов к чужим team_stage_progress
-- добавим, когда будем строить админ-панель — сейчас админ работает
-- через backend на service_role key, который RLS не касается.
