from contextlib import asynccontextmanager
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin_routes import router as admin_router
from app.auth_routes import router as auth_router
from app.routes import router
from app.services.cache_service import close_cache_client
from app.services.ollama_service import close_ollama_session



@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    close_ollama_session()
    close_cache_client()


app = FastAPI(
    title="Sogetrel Knowledge Platform API",
    description="Enterprise AI Knowledge Platform for FDE knowledge base retrieval and chatbot services.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def performance_request_context(request, call_next):
    request.state.performance_started = time.perf_counter()
    request.state.request_id = str(uuid4())
    return await call_next(request)

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
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "message": "Sogetrel Knowledge Platform API",
        "docs": "/docs",
        "health": "/api/v1/health",
    }