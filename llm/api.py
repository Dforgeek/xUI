from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import sys
from pathlib import Path

# Add the current directory to Python path for imports
sys.path.append(str(Path(__file__).parent))

from llm_api import get_summary, ReviewsData
from prompt_lib import USER_PROMPTS, get_user_prompt

# Initialize FastAPI app
app = FastAPI(
    title="Review Summarization API",
    description="API for generating summaries of employee reviews using various LLM models and prompts",
    version="1.0.0"
)

# Request models
class SummarizeRequest(BaseModel):
    """Request model for summarization endpoint"""
    reviews: ReviewsData  # Reviews data in JSON format
    system_prompt: str
    user_prompt: str

class SummarizeResponse(BaseModel):
    """Response model for summarization endpoint"""
    summary: str

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "Review Summarization API is running"}

# Main summarization endpoint
@app.post("/summarize", response_model=SummarizeResponse)
async def summarize_reviews(request: SummarizeRequest):
    """
    Generate a summary of employee reviews
    
    Args:
        request: SummarizeRequest containing reviews data and optional parameters
        
    Returns:
        SummarizeResponse with generated summary and metadata
    """
    try:
        # Validate and convert reviews data
        try:
            reviews_data = ReviewsData.model_validate(request.reviews)
        except Exception as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid reviews data format: {str(e)}"
            )
        
        user_prompt = request.user_prompt
        system_prompt = request.system_prompt
        
        # Generate summary
        try:
            summary = get_summary(
                reviews=reviews_data,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error generating summary: {str(e)}"
            )
        
        return SummarizeResponse(
            summary=summary,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    
    # Set working directory
    os.chdir(Path(__file__).parent)
    
    print("Starting Review Summarization API...")
    print("API Documentation will be available at: http://localhost:8000/docs")
    print("Health check: http://localhost:8000/health")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)