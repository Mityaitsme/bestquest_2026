-- Поля ответа для метода 2 из requirements.md ("кодовое слово" в окошке).
--
-- Order-sensitive/order-insensitive реализовано без специального флага в
-- логике проверки: у каждого поля свой список принятых ответов
-- (answer_field_accepted_values). Для order-sensitive поля туда кладут
-- ответ именно для этого поля; для order-insensitive группы полей одного
-- этапа туда кладут ОДИН И ТОТ ЖЕ общий набор принятых ответов для каждого
-- поля группы — тогда любое поле принимает любое слово из набора, и код
-- проверки остаётся одинаковым в обоих случаях. order_sensitive ниже —
-- только описательное поле для контент-автора, на проверку не влияет.
--
-- Важно: answer_field_accepted_values НЕ должна быть доступна с фронтенда
-- ни в каком виде (иначе участники увидят правильные ответы) — только
-- backend на service_role key.

create table answer_fields (
    id uuid primary key default gen_random_uuid(),
    stage_id uuid not null references stages (id) on delete cascade,
    field_key text not null,
    label text not null,
    hint text not null default '',
    order_position integer not null,
    order_sensitive boolean not null default true,
    unique (stage_id, field_key)
);

create table answer_field_accepted_values (
    id uuid primary key default gen_random_uuid(),
    field_id uuid not null references answer_fields (id) on delete cascade,
    value text not null
);

-- Строка существует, только если команда УЖЕ ответила на это поле правильно
-- (см. auth.py-стиль комментарий в backend/answers.py): неправильные ответы
-- нигде не хранятся, поэтому при повторном открытии окна с сервера
-- подтягиваются только верно отвеченные поля, а остальные остаются пустыми.
create table team_field_submissions (
    team_id uuid not null references teams (id) on delete cascade,
    field_id uuid not null references answer_fields (id) on delete cascade,
    submitted_value text not null,
    submitted_at timestamptz not null default now(),
    primary key (team_id, field_id)
);

alter table answer_fields enable row level security;
alter table answer_field_accepted_values enable row level security;
alter table team_field_submissions enable row level security;

-- Метаданные поля (текст/подсказка) не секрет — команда должна их видеть.
create policy "answer_fields_select_authenticated" on answer_fields
    for select
    using (auth.role() = 'authenticated');

-- Принятые ответы НЕ открываем никому кроме backend (service_role) —
-- политики для answer_field_accepted_values намеренно не создаём.

-- Команда видит только свои собственные верно отвеченные поля.
create policy "team_field_submissions_select_own" on team_field_submissions
    for select
    using (team_id = (select id from teams where auth_user_id = auth.uid()));
