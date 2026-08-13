-- Стабилизация MVP: измерения, сроки хранения, защита от дублей.
-- Схема не переделывается — только добавляются колонки к тому, что есть.

-- ── измерения ────────────────────────────────────────────────
-- Без этих колонок себестоимость ролика невозможно посчитать:
-- всё, что известно сейчас, живёт только в логах контейнера.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS speech_provider TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS speech_ms       INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS speech_words    INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS plan_ms         INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS render_ms       INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_bytes    BIGINT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS output_bytes    BIGINT;

-- ── сроки хранения ───────────────────────────────────────────
-- keep_until ставится в момент готовности: до этой даты ролик
-- лежит на диске, после — уборщик сносит файл и оставляет карточку.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS keep_until        TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_deleted_at TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS output_deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS videos_keep_idx
  ON videos(keep_until) WHERE output_deleted_at IS NULL;

-- ── защита от двойного запуска ───────────────────────────────
-- Клиент присылает один и тот же ключ при повторе запроса.
-- Индекс частичный: у старых строк ключа нет, и это нормально.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS client_token TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS videos_client_token_idx
  ON videos(user_id, client_token) WHERE client_token IS NOT NULL;

-- ── ссылка на скачивание ─────────────────────────────────────
-- Готовый ролик отдаётся по ссылке из чата, а туда initData
-- не подставить. Токен — единственный ключ доступа к файлу.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS share_token TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS videos_share_token_idx
  ON videos(share_token) WHERE share_token IS NOT NULL;

-- ── разбор падений ───────────────────────────────────────────
-- error затирается на каждой попытке, а знать нужно первопричину.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS fail_reason TEXT;
