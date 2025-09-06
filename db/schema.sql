create table user_info
(
    id bigserial primary key,
    telegram_id bigint not null,
    post int not null,
    command_id bigint not null
);

create index user_info_telegram_id_idx on user_info (telegram_id);
create index user_info_command_id_idx on user_info (command_id);

create table survey
(
    id bigserial primary key,
    questions text not null,
    created_at timestamp with time zone not null,
    deadline timestamp with time zone not null
);

create table survey_respondents
(
    id bigserial primary key,
    survey_id bigint not null,
    user_id bigint not null
);

create unique index survey_respondents_survey_id_user_id on survey_respondents (survey_id, user_id);

create table survey_answers
(
    id bigserial primary key,
    survey_id bigint not null,
    user_id bigint not null,
    answer text not null
);

create index survey_answers_survey_id_user_id on survey_answers (survey_id, user_id);
