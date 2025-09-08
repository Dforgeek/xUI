import os
from langchain.chat_models import init_chat_model

if not os.environ.get("DEEPSEEK_API_KEY"):
  os.environ["DEEPSEEK_API_KEY"] = ""

model = init_chat_model("deepseek-chat", model_provider="deepseek")