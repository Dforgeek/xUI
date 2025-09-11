import os
from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model


def get_model(model_name: str):
    """
    Initialize and return a model based on the model name.
    
    Available models:
    - deepseek-reasoning: DeepSeek reasoning model via Pollinations
    - openai-large: OpenAI GPT-4 large via Pollinations  
    - gemini: Gemini model via Pollinations
    - openai: OpenAI GPT model via Pollinations
    - openai-reasoning: OpenAI reasoning model via Pollinations
    """
    
    # Use DeepSeek API directly for deepseek-reasoning and deepseek-chat
    if model_name in ["deepseek-reasoning"]:
        return init_chat_model("deepseek-chat", model_provider="deepseek", api_key=os.environ.get("DEEPSEEK_API_KEY"))
    # All other models use Pollinations
    return ChatOpenAI(
        model=model_name,
        base_url="https://text.pollinations.ai/openai",
        api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-custom-provider")
    )

model = init_chat_model("deepseek-chat", model_provider="deepseek")