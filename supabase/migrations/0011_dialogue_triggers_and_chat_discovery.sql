-- Автотриггер сценарного диалога: стадия, при выполнении которой командой
-- чат с указанным персонажем сам переключается в режим "сценарий" (и
-- становится видимым в поиске команды — см. discovered ниже). Ручное
-- переключение режима оператором через админку (dropdown в чате) остаётся
-- как оверрайд на форс-мажор — эта таблица только про автоматику.
create table stage_dialogue_triggers (
    stage_id uuid not null references stages (id) on delete cascade,
    character_id uuid not null references characters (id) on delete cascade,
    primary key (stage_id, character_id)
);

alter table stage_dialogue_triggers enable row level security;

-- Поиск чатов по нику у команды: чат персонажа не отображается в списке,
-- пока команда сама не введёт верный ник в поиске (или пока чат не
-- "откроется" сюжетным триггером выше) — чат техподдержки виден всегда.
-- default true — уже существующие на момент миграции чаты не прячутся
-- задним числом у команд, которые их уже видели; false проставляется явно
-- в коде при создании НОВЫХ чатов персонажей (backend/chat.py:
-- seed_team_chats, backend/import_content.py: _backfill_existing_teams).
alter table chats add column discovered boolean not null default true;
