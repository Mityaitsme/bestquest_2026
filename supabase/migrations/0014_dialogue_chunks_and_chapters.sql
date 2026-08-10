-- Обобщаем "конец диалога завершает этап" с уровня ПЕРСОНАЖА (0013) на
-- уровень УЗЛА диалога: у персонажа может быть несколько "кусков" истории
-- за квест (не один диалог целиком), и каждый кусок должен уметь завершать
-- СВОЙ этап, а не только единственный на весь диалог. characters.
-- completion_stage_id (0013) ещё не использовался в боевом контенте —
-- просто переносим на dialogue_nodes.
alter table characters drop column completion_stage_id;
alter table dialogue_nodes add column completion_stage_id uuid references stages (id) on delete set null;

-- "Продолжение" диалога (следующий кусок истории) по завершении этапа —
-- в отличие от stage_dialogue_triggers, НЕ включает сценарный режим
-- автоматически. Только молча передвигает указатель команды на нужный
-- узел ("что покажется, когда оператор сам включит режим 'сценарий'
-- через dropdown"); включение режима остаётся полностью ручным действием
-- оператора.
create table stage_dialogue_resumes (
    stage_id uuid not null references stages (id) on delete cascade,
    character_id uuid not null references characters (id) on delete cascade,
    target_node_id uuid not null references dialogue_nodes (id) on delete cascade,
    primary key (stage_id, character_id)
);
alter table stage_dialogue_resumes enable row level security;

-- Короткая подпись на кнопке варианта диалога (например, "Собрание") может
-- отличаться от текста, который реально попадает в чат как "сообщение
-- команды" при нажатии (например, полная фраза "Сегодня у секты будет
-- собрание в парке Сокольники."). Если не задано — используется
-- option_text как раньше (обратная совместимость).
alter table dialogue_options add column sent_message text;

-- Название главы, которую участники сейчас проходят: определяется по
-- этапу с максимальным available_at у команды (последнему ОТКРЫВШЕМУСЯ
-- этапу, а не последнему выполненному).
alter table stages add column chapter text;
alter table team_stage_progress add column available_at timestamptz;
