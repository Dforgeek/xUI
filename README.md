# xUI
Кейс хакатона номер 2, оценка 360


### LLM Docker
Put DeepSeek key in .env file
```
DEEPSEEK_API_KEY=
```
Build and run:
docker build -f Dockerfile.api_llm -t llm-api .
docker run -p 8002:8002 --env-file .env llm-api
