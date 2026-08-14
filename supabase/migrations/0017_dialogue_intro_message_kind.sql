-- Новое значение message_kind для реплик персонажа, доставленных
-- автоматически (см. chat.py: jump_to_node, dialogue.py: _deliver_node_intro) —
-- когда сценарный диалог "оживает" сам (resumes_dialogue_at) и сразу
-- начинается с реплики персонажа, а не с выбора команды. Фронтенд команды
-- отличает такие сообщения, чтобы показывать не самоисчезающий тост, а
-- уведомление, которое остаётся, пока команда не откроет этот чат.

alter table messages
    drop constraint messages_message_kind_check;

alter table messages
    add constraint messages_message_kind_check
        check (message_kind in ('normal', 'support_comment', 'dialogue_intro'));
