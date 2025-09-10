-- user_info
create table if not exists user_info
(
    id bigserial primary key,
    telegram_id bigint not null,
    post int not null,
    command_id bigint not null
);
create index if not exists user_info_telegram_id_idx on user_info (telegram_id);
create index if not exists user_info_command_id_idx on user_info (command_id);

-- block
create table if not exists block
(
    id bigserial primary key,
    block_name varchar(255) not null unique
);

-- question
create table if not exists question
(
    id bigserial primary key,
    block_id bigint not null references block(id) on delete cascade,
    question_text text not null,
    question_type smallint not null,
    answer_fields text not null
);
create index if not exists question_block_id_idx on question (block_id);

-- survey_preset
create table if not exists survey_preset
(
    id bigserial primary key,
    questions bigint[] not null
);

-- survey
create table if not exists survey
(
    id bigserial primary key,
    subject_user_id bigint not null references user_info(id) on delete restrict,
    created_at timestamptz not null,
    deadline    timestamptz not null,
    notifications_before bigint not null,
    anonymous boolean not null default false,
    review_type varchar(10) not null default '180'
);
create index if not exists survey_subject_idx on survey(subject_user_id);

-- survey_question
create table if not exists survey_question
(
    id bigserial primary key,
    question_id bigint not null references question(id) on delete cascade,
    survey_id   bigint not null references survey(id) on delete cascade,
    unique (question_id, survey_id)
);

-- survey_respondent
create table if not exists survey_respondent
(
    id bigserial primary key,
    user_id  bigint not null references user_info(id) on delete cascade,
    survey_id bigint not null references survey(id) on delete cascade,
    unique (user_id, survey_id)
);

-- survey_answer
create table if not exists survey_answer
(
    id bigserial primary key,
    survey_id  bigint not null references survey(id) on delete cascade,
    user_id    bigint not null references user_info(id) on delete cascade,
    question_id bigint not null references question(id) on delete cascade,
    answer     text not null,
    unique (survey_id, user_id, question_id)
);
create index if not exists survey_answer_survey_id_question_id_idx on survey_answer (survey_id, question_id);
