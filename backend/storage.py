"""
Persistance légère des analyses en JSON.
Stocke l'historique des analyses effectuées pour le tableau récapitulatif.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_STORAGE_FILE = os.path.join(os.path.dirname(__file__), "analyses_history.json")
_MAX_ENTRIES = 200  # limite pour éviter un fichier trop grand


def _load() -> list[dict]:
    if not os.path.exists(_STORAGE_FILE):
        return []
    try:
        with open(_STORAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        logger.exception("Lecture cache analyses corrompue : %s", _STORAGE_FILE)
        return []


def _save(entries: list[dict]) -> None:
    with open(_STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, default=str, indent=2)


def save_analysis(result: Any) -> None:
    """
    Sauvegarde un résultat d'analyse dans l'historique.
    `result` est un objet AnalysisResponse (Pydantic) ou un dict.
    """
    if hasattr(result, "model_dump"):
        data = result.model_dump()
    else:
        data = dict(result)

    entries = _load()

    # Calcul de la tendance : comparer avec la dernière analyse du même ticker
    ticker = data.get("ticker", "")
    prev = next((e for e in reversed(entries) if e.get("ticker") == ticker), None)
    prev_score = prev["global_score"] if prev else None
    curr_score = data["global_score"]["total"]

    if prev_score is None:
        trend = "new"
    elif curr_score > prev_score + 1:
        trend = "up"
    elif curr_score < prev_score - 1:
        trend = "down"
    else:
        trend = "stable"

    entry = {
        "ticker": ticker,
        "company_name": data.get("company_name", ""),
        "sector": data.get("sector", ""),
        "global_score": curr_score,
        "prev_score": prev_score,
        "trend": trend,
        "zone": data.get("valorisation", {}).get("zone_result", {}).get("zone", ""),
        "date": data.get("last_updated", datetime.now(timezone.utc).isoformat()),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    # Dé-dupliquer: on ajoute quand même (historique, pas upsert)
    entries.append(entry)

    # Conserver seulement les _MAX_ENTRIES dernières
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]

    _save(entries)


def get_all() -> list[dict]:
    """Retourne toutes les analyses, de la plus récente à la plus ancienne."""
    entries = _load()
    return list(reversed(entries))
