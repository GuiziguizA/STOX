# Backend — API Analyse Financière

FastAPI backend pour l'application d'analyse de marché boursier.

## Installation

```bash
cd backend
pip install -r requirements.txt
```

## Lancement

```bash
uvicorn main:app --reload --port 8000
```

Documentation Swagger : http://localhost:8000/docs

## Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/health` | Health check |
| GET | `/analyze/{ticker}` | Analyse complète en JSON |
| GET | `/analyze/{ticker}/stream` | Analyse avec progression SSE |

## Structure

```
backend/
├── main.py                    # App FastAPI + CORS
├── requirements.txt
├── api/
│   └── routes.py              # Endpoints REST + SSE
├── scraping/
│   └── yfinance_scraper.py    # Scraping yfinance + cache 24h
├── analysis/
│   ├── rentabilite.py         # Score rentabilité (30%)
│   ├── solidite.py            # Score solidité financière (25%)
│   ├── flux.py                # Score flux de trésorerie (20%)
│   └── valorisation.py        # Score valorisation + zones (25%)
└── models/
    └── schemas.py             # Pydantic schemas
```

## Score global

```
Score final = (Rentabilité × 30%) + (Solidité × 25%) + (Flux × 20%) + (Valorisation × 25%)
```

Interprétation :
- 90–100 : Excellence financière
- 75–89 : Très solide
- 60–74 : Correct mais améliorable
- 40–59 : Fragile
- < 40 : Situation préoccupante

## Zones de valorisation

4 méthodes croisées → zone consensus :
- **Solde** : décote significative, forte marge de sécurité
- **Attractif** : valorisation raisonnable
- **Fair Value** : juste prix
- **Cher** : prime de valorisation, risque de correction

## Cache

Les données yfinance sont cachées 24h en mémoire + fichier JSON dans `.cache/`.
