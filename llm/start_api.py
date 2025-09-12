import os
import sys
from pathlib import Path
import uvicorn

def start_api():
    """Start the FastAPI server"""
    # Set working directory
    os.chdir(Path(__file__).parent)
 
    print("Starting Review Summarization API...")
    print("Health check: http://localhost:8000/health")
    print("-" * 50)
        
    uvicorn.run(
        "api:app",  # This is the import string format
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        reload_dirs=[str(Path(__file__).parent)]  # Watch the llm directory for changes
    )
        

if __name__ == "__main__":
    start_api()