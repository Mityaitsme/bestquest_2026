-- Отдельное поле для системного промпта персонажа (для ChatGPT), отдельно
-- от public_lore. public_lore — то, что можно показать игроку (например,
-- био персонажа); gpt_persona_prompt — только для самой модели, игрок его
-- никогда не видит: как персонаж говорит, что он знает и не должен
-- раскрывать и т.п.

alter table characters
    add column gpt_persona_prompt text not null default '';
