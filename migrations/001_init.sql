-- Схема Reels Studio. Применяется автоматически при старте (server/db.js).

CREATE TABLE IF NOT EXISTS users (
  id          BIGSERIAL PRIMARY KEY,
  tg_id       BIGINT UNIQUE NOT NULL,
  username    TEXT,
  first_name  TEXT,
  last_name   TEXT,
  photo_url   TEXT,

  -- Кредит — это один ролик. Списывается по факту рендера.
  credits     NUMERIC(10,2) NOT NULL DEFAULT 0,
  -- Пакет живёт ограниченный срок, иначе лимиты копятся вечно
  -- и однажды кто-то обналичивает триста роликов разом.
  expires_at  TIMESTAMPTZ,

  ref_code    TEXT UNIQUE NOT NULL,
  referred_by BIGINT REFERENCES users(id),
  ref_rewarded BOOLEAN NOT NULL DEFAULT FALSE,

  is_admin    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Любое движение кредитов оставляет строку. Без этого невозможно
-- ответить клиенту, куда делись его ролики.
CREATE TABLE IF NOT EXISTS ledger (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  delta      NUMERIC(10,2) NOT NULL,
  balance    NUMERIC(10,2) NOT NULL,
  reason     TEXT NOT NULL,
  ref        TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ledger_user_idx ON ledger(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS payments (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  package_code TEXT NOT NULL,
  credits      INTEGER NOT NULL,
  amount       NUMERIC(10,2) NOT NULL,
  currency     TEXT NOT NULL DEFAULT 'RUB',
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending | paid | failed
  provider     TEXT NOT NULL DEFAULT 'lava',
  invoice_id   TEXT,
  pay_url      TEXT,
  raw          JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  paid_at      TIMESTAMPTZ
);
-- Защита от двойного начисления, если касса пришлёт вебхук дважды.
CREATE UNIQUE INDEX IF NOT EXISTS payments_invoice_idx
  ON payments(provider, invoice_id) WHERE invoice_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS payments_user_idx ON payments(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS videos (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title         TEXT NOT NULL DEFAULT 'Без названия',
  status        TEXT NOT NULL DEFAULT 'draft',  -- draft|queued|running|ready|failed
  template      TEXT NOT NULL DEFAULT 'expose',
  brief         TEXT,
  reference_url TEXT,

  source_path   TEXT,
  output_path   TEXT,
  poster_path   TEXT,
  duration_sec  NUMERIC(8,2),

  -- Разметка: реплики, акценты, врезки. Сейчас её собирает шаблон,
  -- позже — модель. Формат один, потребитель (рендер) не меняется.
  plan          JSONB,

  preview_only  BOOLEAN NOT NULL DEFAULT FALSE,
  cost          NUMERIC(10,2) NOT NULL DEFAULT 1,
  parent_id     BIGINT REFERENCES videos(id) ON DELETE SET NULL,
  error         TEXT,

  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS videos_user_idx ON videos(user_id, created_at DESC);

-- Метки правок с точным таймкодом — из редактора мини-аппа.
CREATE TABLE IF NOT EXISTS marks (
  id         BIGSERIAL PRIMARY KEY,
  video_id   BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  at_sec     NUMERIC(8,2) NOT NULL,
  note       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS marks_video_idx ON marks(video_id, at_sec);

-- Очередь на Postgres вместо Redis: одна зависимость вместо двух,
-- а SELECT ... FOR UPDATE SKIP LOCKED честно разводит воркеры.
CREATE TABLE IF NOT EXISTS jobs (
  id          BIGSERIAL PRIMARY KEY,
  video_id    BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
  attempts    INTEGER NOT NULL DEFAULT 0,
  progress    INTEGER NOT NULL DEFAULT 0,
  stage       TEXT,
  error       TEXT,
  run_after   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  locked_at   TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS jobs_pick_idx ON jobs(status, run_after);
