from init_model import model, get_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers.string import StrOutputParser

from models import ReviewsData


def convert_reviews_to_text(data: ReviewsData) -> str:
    """
    Преобразует JSON с отзывами в структурированный текст для LLM.

    Формат:
    <review>
    <title>Название раздела</title>
    Текст раздела
    ...
    </review>
    """
    reviews_texts = []

    for review in data.reviews:
        sections_texts = []
        for section in review.sections:
            title = section.title.strip()
            text = section.text.strip()
            if title and text:
                sections_texts.append(f"<title>{title}</title>\n{text}")
        if sections_texts:
            review_text = "<review>\n" + "\n\n".join(sections_texts) + "\n</review>"
            reviews_texts.append(review_text)

    return "\n\n".join(reviews_texts)


def get_summary(reviews: ReviewsData, system_prompt: str | None, user_prompt: str | None, model_name: str = None) -> str:
    """
    Generates a summary of reviews using LLM.

    Args:
        reviews (ReviewsData): Review data containing all reviews and sections.
        system_prompt (str | None): System prompt for the model. If None, default will be used.
        user_prompt (str | None): User prompt for the model. If None, default will be used.
        model_name (str): Name of the model to use. If None, default model will be used.

    Returns:
        str: Generated summary of the reviews.
    """
    reviews_text = convert_reviews_to_text(reviews)

    if not system_prompt:
        with open("prompts/system.txt", "r") as file:
            system_prompt = file.read()
    if not user_prompt:
        with open("prompts/basic_user.txt", "r") as file:
            user_prompt = file.read()

    # Use specified model or default
    selected_model = get_model(model_name) if model_name else model

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", user_prompt)
    ])

    mes_parser = StrOutputParser()
    runnable = prompt | selected_model | mes_parser

    summary = runnable.invoke({"reviews": reviews_text})

    return summary