from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router


app = FastAPI(
    title="Sogetrel Knowledge Platform API",
    description="Enterprise AI Knowledge Platform for FDE knowledge base retrieval and chatbot services.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "message": "Sogetrel Knowledge Platform API",
        "docs": "/docs",
        "health": "/api/v1/health",
    }