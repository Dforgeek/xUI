# xUI
Кейс хакатона номер 2, оценка 360

## Quick Start

### Frontend
```
cd .\survey-ui\
docker build -t survey-ui .
docker run --rm -p 5173:80 survey-ui
```


### Backend 
```
docker-compose up
```
По localhost:8000/docs будет доступен swagger

### LLM Docker
Put DeepSeek key in .env file
```
DEEPSEEK_API_KEY=
```
Build and run:
docker build -f Dockerfile.api_llm -t llm-api .
docker run -p 8002:8002 --env-file .env llm-api



#### Команда xUI
1) Михаил Степановский
2) Владислав Попов
3) Михаил Лопатин
4) Степан Романенко
