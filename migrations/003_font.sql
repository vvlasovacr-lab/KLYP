-- Шрифт субтитров, выбранный клиентом. Пусто — подбирается системой
-- под шаблон монтажа.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS font TEXT;
