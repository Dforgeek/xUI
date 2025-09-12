-- =====================================================================
-- ONE-BLOCK SURVEY — CLEAN SCHEMA
-- Personal per-respondent surveys + tokenized access + JSONB responses
-- =====================================================================

-- (Optional) If you're OK to wipe everything:
-- DROP SCHEMA public CASCADE;
-- CREATE SCHEMA public;

-- ----------------------
-- Core directory tables
-- ----------------------
create table if not exists user_info
(
    id bigserial primary key,
    telegram_id bigint not null,
    post int not null,
    command_id bigint not null,

    -- personal fields used by the envelope (nullable, easy to backfill)
    first_name varchar(100),
    last_name  varchar(100),
    email      varchar(255),
    telegram   varchar(64)
);
create index if not exists user_info_telegram_id_idx on user_info (telegram_id);
create index if not exists user_info_command_id_idx on user_info (command_id);
create index if not exists user_info_email_idx      on user_info (email);
create index if not exists user_info_telegram_idx   on user_info (telegram);

create table if not exists block
(
    id bigserial primary key,
    block_name varchar(255) not null unique
);

create table if not exists question
(
    id bigserial primary key,
    block_id bigint not null references block(id) on delete cascade,
    question_text text not null,
    question_type smallint not null,  -- 1=rating, else=text (your code maps like that)
    answer_fields text not null       -- JSON with min/max/placeholder/minLength when relevant
);
create index if not exists question_block_id_idx on question (block_id);

create table if not exists survey_preset
(
    id bigserial primary key,
    questions bigint[] not null
);

-- ----------------------
-- Personal survey model
-- ----------------------
create table if not exists survey
(
    id bigserial primary key,

    -- review subject (the person being reviewed)
    subject_user_id bigint not null references user_info(id) on delete restrict,

    -- NEW: personal respondent for this specific survey instance
    respondent_user_id bigint not null references user_info(id) on delete restrict,

    created_at timestamptz not null,
    deadline   timestamptz not null,

    notifications_before bigint not null,
    anonymous boolean not null default false,
    review_type varchar(10) not null default '180',

    -- optional title for envelope
    title varchar(255)
);
create index if not exists survey_subject_idx    on survey(subject_user_id);
create index if not exists survey_respondent_idx on survey(respondent_user_id);

create table if not exists survey_question
(
    id bigserial primary key,
    question_id bigint not null references question(id) on delete cascade,
    survey_id   bigint not null references survey(id)   on delete cascade,
    optional boolean not null default false,

    unique (question_id, survey_id)
);

-- --------------------------------------
-- Tokenized access + JSONB answer store
-- --------------------------------------
create table if not exists survey_link_token
(
    id bigserial primary key,
    token varchar(128) not null unique,
    survey_id bigint not null references survey(id) on delete cascade,
    respondent_user_id bigint not null references user_info(id) on delete cascade,
    created_at timestamptz not null,
    last_access_at timestamptz,
    is_revoked boolean not null default false
);
create index if not exists survey_link_token_token_idx on survey_link_token(token);

create table if not exists survey_response
(
    id bigserial primary key,
    survey_id bigint not null references survey(id) on delete cascade,
    respondent_user_id bigint not null references user_info(id) on delete cascade,

    link_token varchar(128) not null,      -- redundant but handy for audits
    version bigint not null default 1,

    answers jsonb not null default '{}',    -- map block.id -> value (int/string/null)
    submitted_at timestamptz,
    updated_at timestamptz,
    finalized boolean not null default false,

    unique (survey_id, respondent_user_id)
);
create index if not exists survey_response_survey_idx on survey_response(survey_id);
create index if not exists survey_response_user_idx   on survey_response(respondent_user_id);

-- --------------------------------------
-- (Optional) Legacy tables — not needed
-- --------------------------------------
-- If you want a *clean* schema, you can drop these:
--   survey_respondent
--   survey_answer
-- They are superseded by per-respondent Survey rows and survey_response JSONB.


-- =========================
-- Batches (group per subject/run) + Summaries
-- =========================

create table if not exists survey_batch
(
    id bigserial primary key,
    subject_user_id bigint not null references user_info(id) on delete restrict,
    review_type varchar(10) not null default '180',
    title varchar(255),
    created_at timestamptz not null,
    deadline   timestamptz not null,
    notifications_before bigint not null default 0,
    anonymous boolean not null default false,

    expected_respondents int not null,
    unique (subject_user_id, created_at) -- practical de-dup guard for same-second runs
);
create index if not exists survey_batch_subject_idx on survey_batch(subject_user_id);
create index if not exists survey_batch_deadline_idx on survey_batch(deadline);

-- ALTER survey to link to batch
alter table if exists survey
    add column if not exists batch_id bigint references survey_batch(id) on delete cascade;

create index if not exists survey_batch_id_idx on survey(batch_id);

-- Summaries
create table if not exists review_summary
(
    id bigserial primary key,
    batch_id bigint not null references survey_batch(id) on delete cascade,
    subject_user_id bigint not null references user_info(id) on delete restrict,

    status varchar(16) not null,          -- queued | running | succeeded | failed
    model_name varchar(128),
    prompt_version int,
    summary_text text,
    stats jsonb,                           -- aggregated numbers, per-question breakdown, etc.
    error text,

    created_at timestamptz not null,
    updated_at timestamptz not null,
    started_at timestamptz,
    completed_at timestamptz,

    unique (batch_id) -- 1 final summary per batch; relax if you want multiple versions
);
create index if not exists review_summary_subject_idx on review_summary(subject_user_id);
create index if not exists review_summary_status_idx  on review_summary(status);
