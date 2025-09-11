# xUI
Кейс хакатона номер 2, оценка 360


### LLM Docker
Put DeepSeek key in .env file
```
DEEPSEEK_API_KEY=
```
Build and run:
docker build -t llm-api
docker run -p 8000:8000 --env-file .env llm-api