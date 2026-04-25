"""
Application FastAPI principale — API d'analyse financière.

Lancement :
    uvicorn main:app --reload --port 8000

Endpoints :
    GET /health                        Health check
    GET /analyze/{ticker}              Analyse complète (JSON)
    GET /analyze/{ticker}/stream       Analyse avec progression SSE
"""
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("backend_errors.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

app = FastAPI(
    title="API Analyse Financière",
    description=(
        "Backend Python pour l'application d'analyse de marché. "
        "Scraping yfinance + scoring (Rentabilité, Solidité, Flux, Valorisation) "
        "selon le framework analyse_entreprise."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS pour le frontend Next.js (développement et production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logging.getLogger("uvicorn.error").error("Unhandled exception on %s: %s\n%s", request.url, exc, tb)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}", "traceback": tb},
    )


app.include_router(router)
