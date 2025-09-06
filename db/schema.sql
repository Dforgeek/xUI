create table user_info
(
    id bigserial primary key,
    telegram_id bigint not null,
    post int not null,
    command_id bigint not null
);
create index user_info_telegram_id_idx on user_info (telegram_id);
create index user_info_command_id_idx on user_info (command_id);

create table block
(
    id bigserial primary key,
    block_name varchar(255) not null
);

create table question
(
    id bigserial primary key,
    block_id bigint not null,
    question_text text not null,
    question_type smallint not null,
    answer_fields text not null
);
create index question_block_id_idx on question (block_id);

create table survey
(
    id bigserial primary key,
    subject_user_id bigint not null,
    created_at timestamp with time zone not null,
    deadline timestamp with time zone not null,
    notifications_before bigint not null
);

create table survey_question
(
    id bigserial primary key,
    question_id bigint not null,
    survey_id bigint not null
);
create unique index survey_question_survey_id_question_id_idx on survey_question (question_id, survey_id);

create table survey_respondent
(
    id bigserial primary key,
    user_id bigint not null,
    survey_id bigint not null
);
create unique index survey_respondent_user_id_survey_id_idx on survey_respondent (user_id, survey_id);

create table survey_answer
(
    id bigserial primary key,
    survey_id bigint not null,
    user_id bigint not null,
    question_id bigint not null,
    answer text not null
);
create index survey_answer_survey_id_question_id_idx on survey_answer (survey_id, question_id);