-- Блок-посты переехали с уровня варианта на уровень узла диалога.
-- Раньше: команда сама выбирала готовую реплику персонажа (вариант),
-- оператор только одобрял/отклонял уже выбранное. Теперь: узел сам
-- помечен как блок-пост — команда видит "печатает..." без кнопок выбора,
-- а оператор в моменте либо выбирает один из заранее написанных вариантов
-- реплики, либо пишет свою, и с этим текстом дальше идёт единый next_node_id
-- узла (тот же столбец, что уже использует requires_all_options).

alter table dialogue_nodes add column is_block_post boolean not null default false;

alter table dialogue_options drop column requires_admin_approval;

drop table dialogue_approvals;
