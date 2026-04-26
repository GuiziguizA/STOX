"""Projet Action — API V4 v2."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as analyze_router

app = FastAPI(title="Projet Action API", version="4.0.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "version": "4.0.0"}
