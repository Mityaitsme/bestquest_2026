-- До сих пор ничего не отличало "этап, который отмечает только админ"
-- (метод 1) от "этап, который команда подтверждает сама" (метод 3) —
-- у обоих просто не было записей в answer_fields. Явно фиксируем тип
-- этапа, чтобы фронтенд знал, какой интерфейс показывать, и чтобы
-- backend мог проверить, что участник вызывает подходящий для этого
-- этапа способ завершения.
--
-- Значения совпадают со словарём completion_method в team_stage_progress.

alter table stages
    add column completion_type text not null default 'actor'
        check (completion_type in ('actor', 'answer', 'checkbox', 'manual_review'));
