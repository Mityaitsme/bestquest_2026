-- Ручная проверка ответа (метод 4 из requirements.md): команда отправляет
-- текст и/или фото, оператор принимает/отклоняет с опциональным комментарием.
--
-- Сама очередь ("вкладка Верификация") реализована как отдельная таблица,
-- а не как часть общей системы чатов (которую мы ещё не строили) — админ-UI
-- сможет отрисовать её в чат-подобном виде позже, без изменения этой схемы.

create table manual_reviews (
    id uuid primary key default gen_random_uuid(),
    team_id uuid not null references teams (id) on delete cascade,
    stage_id uuid not null references stages (id) on delete cascade,
    submitted_text text not null default '',
    photo_path text,
    status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
    reviewer_admin_id uuid references admins (id) on delete set null,
    comment text,
    created_at timestamptz not null default now(),
    reviewed_at timestamptz
);

alter table manual_reviews enable row level security;

-- Команда видит только свои собственные заявки на проверку.
create policy "manual_reviews_select_own" on manual_reviews
    for select
    using (team_id = (select id from teams where auth_user_id = auth.uid()));

-- Заявки от других команд и работу оператора (принять/отклонить) пока ведём
-- только через backend на service_role key — как и с остальными таблицами.
