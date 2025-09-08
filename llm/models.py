from pydantic import BaseModel

class ReviewSection(BaseModel):
    """Model for a review section"""
    title: str
    text: str


class Review(BaseModel):
    """Model for a single review"""
    sections: list[ReviewSection]


class ReviewsData(BaseModel):
    """Model for all reviews"""
    reviews: list[Review]
