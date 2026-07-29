-- Режим сравнения принятого ответа: exact (по умолчанию, как раньше) или
-- contains — засчитывается, если это значение встречается ПОДСТРОКОЙ в
-- ответе команды (например, ключевые слова "кружк"/"чашк" совпадут с
-- "кружка", "чашка - улика", "дело в кружке" и т.п.).

alter table answer_field_accepted_values
    add column match_mode text not null default 'exact'
        check (match_mode in ('exact', 'contains'));
