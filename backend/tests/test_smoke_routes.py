"""Test smoke — vérifie que les routes critiques sont bien montées au démarrage.

Exécution sans dépendances externes (pas de BDD, pas de réseau) :
  cd backend && pytest tests/test_smoke_routes.py -v
"""
import sys
import os

# Assure que le dossier backend/ est dans sys.path pour les imports de main.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from main import app

CRITICAL_ROUTES = {
    ("GET", "/analyze/{ticker}"),
    ("GET", "/analyze/{ticker}/stream"),
    ("GET", "/search"),
    ("GET", "/analyses"),
    ("GET", "/health"),
}


def _registered_routes() -> set[tuple[str, str]]:
    result = set()
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                result.add((method, route.path))
    return result


def test_critical_routes_registered():
    """Toutes les routes critiques doivent être exposées par l'app."""
    registered = _registered_routes()
    missing = CRITICAL_ROUTES - registered
    assert not missing, (
        f"Routes critiques manquantes dans l'app : {missing}\n"
        f"Routes enregistrées : {registered}"
    )


def test_health_endpoint():
    """Le endpoint /health doit répondre 200."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"
