-- Автозавершение задачи по концу сценарного диалога: у персонажа теперь
-- можно указать этап, который сам отмечается выполненным для команды, когда
-- её диалог с этим персонажем доходит до последнего узла (next_node_id
-- отсутствует) — см. backend/dialogue.py: _advance_to/_complete_linked_stage.
-- Симметрично stage_dialogue_triggers (0011): там этап включает диалог,
-- здесь диалог завершает этап.
alter table characters
    add column completion_stage_id uuid references stages (id) on delete set null;

-- Новый completion_type/completion_method: 'dialogue' — этап, который
-- никто не отмечает вручную, его закрывает конец сценарного диалога
-- (characters.completion_stage_id выше).
alter table stages drop constraint stages_completion_type_check;
alter table stages add constraint stages_completion_type_check
    check (completion_type in ('actor', 'answer', 'checkbox', 'manual_review', 'dialogue'));

alter table team_stage_progress drop constraint team_stage_progress_completion_method_check;
alter table team_stage_progress add constraint team_stage_progress_completion_method_check
    check (completion_method in ('actor', 'answer', 'checkbox', 'manual_review', 'dialogue'));
