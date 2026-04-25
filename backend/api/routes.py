"""
Routes FastAPI pour l'API d'analyse financière.
"""
import asyncio
import json
import time
from datetime import datetime
from typing import AsyncGenerator

import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from analysis import flux, rentabilite, solidite, valorisation
from models.schemas import AnalysisResponse, ErrorResponse, GlobalScore
from scraping.yfinance_scraper import scrape_ticker
import storage

router = APIRouter()


def _global_score(r_score: float, s_score: float, f_score: float, v_score: float) -> GlobalScore:
    total = (r_score * 0.30) + (s_score * 0.25) + (f_score * 0.20) + (v_score * 0.25)

    if total >= 90:
        interp = "Excellence financière"
    elif total >= 75:
        interp = "Très solide"
    elif total >= 60:
        interp = "Correct mais améliorable"
    elif total >= 40:
        interp = "Fragile"
    else:
        interp = "Situation préoccupante"

    return GlobalScore(
        total=round(total, 1),
        rentabilite=r_score,
        solidite=s_score,
        flux=f_score,
        valorisation=v_score,
        interpretation=interp,
    )


def _key_metrics(data: dict, r, s, f, v) -> dict:
    """Construit le dict des métriques clés pour le dashboard."""
    def fmt_pct(v, decimals=1):
        return f"{v * 100:.{decimals}f}%" if v is not None else "N/A"

    def fmt_float(v, decimals=2):
        return f"{v:.{decimals}f}" if v is not None else "N/A"

    def fmt_money(v):
        if v is None:
            return "N/A"
        if abs(v) >= 1e9:
            return f"{v / 1e9:.2f} Md"
        if abs(v) >= 1e6:
            return f"{v / 1e6:.1f} M"
        return f"{v:.0f}"

    return {
        "prix_actuel": fmt_float(data.get("current_price")),
        "capitalisation": fmt_money(data.get("market_cap")),
        "per": fmt_float(data.get("per"), 1),
        "marge_nette": fmt_pct(data.get("net_margin")),
        "marge_operationnelle": fmt_pct(data.get("operating_margin")),
        "roe": fmt_pct(data.get("roe")),
        "roa": fmt_pct(data.get("roa")),
        "cagr_ca": fmt_pct(data.get("revenue_cagr_10y")),
        "dette_nette_ebitda": fmt_float(data.get("net_debt_ebitda"), 2),
        "fcf": fmt_money(data.get("fcf")),
        "fcf_yield": fmt_pct(data.get("fcf_yield")),
        "rendement_dividende": fmt_pct(data.get("dividend_yield")),
        "zone_valorisation": v.zone_result.zone,
        "fair_value": fmt_float(v.zone_result.fair_value_estimate, 2),
        "marge_securite": f"{v.zone_result.safety_margin_pct:.1f}%" if v.zone_result.safety_margin_pct else "N/A",
        "score_global": r.score * 0.30 + s.score * 0.25 + f.score * 0.20 + v.score * 0.25,
    }


@router.get(
    "/analyze/{ticker}",
    response_model=AnalysisResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Analyse financière complète d'un ticker",
    description=(
        "Lance le scraping via yfinance puis calcule le score global pondéré "
        "(Rentabilité 30%, Solidité 25%, Flux 20%, Valorisation 25%) "
        "avec les zones de valorisation selon le framework analyse_entreprise."
    ),
)
async def analyze(ticker: str):
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Ticker invalide.")

    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, scrape_ticker, ticker
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur scraping : {e}")

    try:
        r = rentabilite.compute(data)
        s = solidite.compute(data)
        f = flux.compute(data)
        v = valorisation.compute(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur analyse : {e}")

    g = _global_score(r.score, s.score, f.score, v.score)
    km = _key_metrics(data, r, s, f, v)

    response = AnalysisResponse(
        ticker=data["ticker"],
        company_name=data["company_name"],
        currency=data["currency"],
        sector=data.get("sector"),
        industry=data.get("industry"),
        last_updated=data["last_updated"],
        global_score=g,
        rentabilite=r,
        solidite=s,
        flux=f,
        valorisation=v,
        key_metrics=km,
    )
    storage.save_analysis(response)
    return response


@router.get(
    "/analyze/{ticker}/stream",
    summary="Analyse financière avec progression SSE",
    description=(
        "Même analyse que /analyze/{ticker} mais retourne les résultats "
        "progressivement via Server-Sent Events (SSE) pour l'affichage "
        "d'une barre de progression côté frontend."
    ),
)
async def analyze_stream(ticker: str):
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Ticker invalide.")

    async def event_stream() -> AsyncGenerator[str, None]:
        def send(step: str, message: str, progress: int, data: dict = None) -> str:
            payload = {"step": step, "message": message, "progress": progress}
            if data:
                payload["data"] = data
            return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        yield send("init", f"Démarrage de l'analyse pour {ticker}...", 0)
        await asyncio.sleep(0)

        # 1. Scraping
        yield send("scraping", "Récupération des données financières (yfinance)...", 10)
        await asyncio.sleep(0)

        try:
            loop = asyncio.get_event_loop()
            scrape_data = await loop.run_in_executor(None, scrape_ticker, ticker)
        except ValueError as e:
            yield send("error", str(e), 0, {"error": str(e)})
            return
        except Exception as e:
            yield send("error", f"Erreur scraping : {e}", 0, {"error": str(e)})
            return

        yield send("scraping", f"Données récupérées pour {scrape_data['company_name']}", 25)
        await asyncio.sleep(0)

        # 2. Rentabilité
        yield send("rentabilite", "Calcul du score de rentabilité (30%)...", 35)
        await asyncio.sleep(0)
        try:
            r = rentabilite.compute(scrape_data)
        except Exception as e:
            yield send("error", f"Erreur rentabilité : {e}", 0)
            return
        yield send("rentabilite", f"Score rentabilité : {r.score}/100", 50, {"score": r.score})
        await asyncio.sleep(0)

        # 3. Solidité
        yield send("solidite", "Calcul du score de solidité financière (25%)...", 55)
        await asyncio.sleep(0)
        try:
            s = solidite.compute(scrape_data)
        except Exception as e:
            yield send("error", f"Erreur solidité : {e}", 0)
            return
        yield send("solidite", f"Score solidité : {s.score}/100", 65, {"score": s.score})
        await asyncio.sleep(0)

        # 4. Flux
        yield send("flux", "Calcul du score de flux de trésorerie (20%)...", 70)
        await asyncio.sleep(0)
        try:
            f = flux.compute(scrape_data)
        except Exception as e:
            yield send("error", f"Erreur flux : {e}", 0)
            return
        yield send("flux", f"Score flux : {f.score}/100", 80, {"score": f.score})
        await asyncio.sleep(0)

        # 5. Valorisation
        yield send("valorisation", "Calcul des zones de valorisation (25%)...", 85)
        await asyncio.sleep(0)
        try:
            v = valorisation.compute(scrape_data)
        except Exception as e:
            yield send("error", f"Erreur valorisation : {e}", 0)
            return
        yield send(
            "valorisation",
            f"Zone : {v.zone_result.zone} | Score : {v.score}/100",
            92,
            {"score": v.score, "zone": v.zone_result.zone},
        )
        await asyncio.sleep(0)

        # 6. Score global
        g = _global_score(r.score, s.score, f.score, v.score)
        km = _key_metrics(scrape_data, r, s, f, v)

        response = AnalysisResponse(
            ticker=scrape_data["ticker"],
            company_name=scrape_data["company_name"],
            currency=scrape_data["currency"],
            sector=scrape_data.get("sector"),
            industry=scrape_data.get("industry"),
            last_updated=scrape_data["last_updated"],
            global_score=g,
            rentabilite=r,
            solidite=s,
            flux=f,
            valorisation=v,
            key_metrics=km,
        )

        storage.save_analysis(response)

        yield send(
            "done",
            f"Analyse terminée — Score global : {g.total}/100 ({g.interpretation})",
            100,
            {"result": response.model_dump()},
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


_SEARCH_ALLOWED_TYPES = {"EQUITY", "ETF", "MUTUALFUND"}

# Types que Yahoo Finance peut renvoyer mais qui ne sont pas analysables
_SEARCH_EXCLUDED_TYPES = {"INDEX", "CURRENCY", "CRYPTOCURRENCY", "FUTURE", "OPTION"}


@router.get(
    "/search",
    summary="Recherche de tickers par nom ou symbole",
    description=(
        "Recherche des entreprises cotées en bourse à partir d'un nom ou d'un symbole. "
        "Permet de trouver 'ATE.PA' en tapant 'alten', ou 'LVMH.PA' en tapant 'LVMH'."
    ),
)
async def search(q: str = Query(..., min_length=1, max_length=100, description="Nom ou symbole à rechercher")):
    q = q.strip()
    if not q:
        return {"results": []}
    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, lambda: yf.Search(q, max_results=10).quotes)
    except Exception as exc:
        # Logger l'erreur mais retourner une liste vide plutôt qu'une 500
        import logging
        logging.getLogger(__name__).warning("yf.Search('%s') a échoué : %s", q, exc)
        return {"results": []}

    if not raw:
        return {"results": []}

    results = []
    for item in raw:
        symbol = item.get("symbol", "")
        if not symbol:
            continue
        name = item.get("shortname") or item.get("longname") or symbol
        exchange = item.get("exchDisp") or item.get("exchange") or ""
        type_ = (item.get("quoteType") or "").upper()
        # Exclure les types non-analysables (indices, devises, futures...)
        # Accepter EQUITY, ETF, MUTUALFUND et tout type inconnu avec un symbole valide
        if type_ in _SEARCH_EXCLUDED_TYPES:
            continue
        results.append({"symbol": symbol, "name": name, "exchange": exchange})
        if len(results) >= 8:
            break
    return {"results": results}


@router.get(
    "/analyses",
    summary="Historique des analyses effectuées",
    description="Retourne la liste des analyses effectuées, de la plus récente à la plus ancienne.",
)
async def get_analyses():
    entries = storage.get_all()
    return {"analyses": entries, "total": len(entries)}


@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
