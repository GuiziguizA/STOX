"""
Module d'analyse de la Rentabilité (poids 30% du score global).

Critères scorés :
- CAGR chiffre d'affaires 10 ans
- CAGR BNA 10 ans
- CAGR dividende 10 ans
- Marge brute
- Marge opérationnelle
- Marge nette
- ROE
- ROA
- PER (penalise si survalorisé)
"""
from typing import Optional

from models.schemas import RentabiliteMetrics, RentabiliteScore


def _score_cagr_revenue(cagr: Optional[float]) -> tuple[float, str]:
    """Scoring CAGR CA 10 ans. Plein score si ≥ 10% / an."""
    if cagr is None:
        return 50.0, "Données CAGR CA indisponibles"
    pct = cagr * 100
    if pct >= 10:
        return 100.0, f"CAGR CA excellent : {pct:.1f}% / an"
    if pct >= 7:
        return 80.0, f"CAGR CA solide : {pct:.1f}% / an"
    if pct >= 4:
        return 60.0, f"CAGR CA modéré : {pct:.1f}% / an"
    if pct >= 0:
        return 35.0, f"CAGR CA faible : {pct:.1f}% / an"
    return 10.0, f"CAGR CA négatif : {pct:.1f}% / an"


def _score_cagr_eps(cagr: Optional[float]) -> tuple[float, str]:
    """Scoring CAGR BNA 10 ans."""
    if cagr is None:
        return 50.0, "Données CAGR BNA indisponibles"
    pct = cagr * 100
    if pct >= 10:
        return 100.0, f"CAGR BNA excellent : {pct:.1f}% / an"
    if pct >= 6:
        return 75.0, f"CAGR BNA solide : {pct:.1f}% / an"
    if pct >= 3:
        return 55.0, f"CAGR BNA modéré : {pct:.1f}% / an"
    if pct >= 0:
        return 30.0, f"CAGR BNA faible : {pct:.1f}% / an"
    return 10.0, f"CAGR BNA négatif : {pct:.1f}% / an"


def _score_cagr_dividend(cagr: Optional[float]) -> tuple[float, str]:
    """Scoring CAGR dividende 10 ans. Bonus si croissant régulièrement."""
    if cagr is None:
        return 50.0, "Données CAGR dividende indisponibles (ou pas de dividende)"
    pct = cagr * 100
    if pct >= 8:
        return 100.0, f"Dividende en forte croissance : {pct:.1f}% / an"
    if pct >= 5:
        return 80.0, f"Dividende en bonne croissance : {pct:.1f}% / an"
    if pct >= 2:
        return 60.0, f"Dividende en légère croissance : {pct:.1f}% / an"
    if pct >= 0:
        return 40.0, f"Dividende stable : {pct:.1f}% / an"
    return 15.0, f"Dividende en baisse : {pct:.1f}% / an"


def _score_gross_margin(margin: Optional[float]) -> tuple[float, str]:
    """Scoring marge brute."""
    if margin is None:
        return 50.0, "Marge brute indisponible"
    pct = margin * 100
    if pct >= 60:
        return 100.0, f"Marge brute excellente : {pct:.1f}%"
    if pct >= 40:
        return 80.0, f"Marge brute élevée : {pct:.1f}%"
    if pct >= 25:
        return 60.0, f"Marge brute correcte : {pct:.1f}%"
    if pct >= 15:
        return 40.0, f"Marge brute faible : {pct:.1f}%"
    return 20.0, f"Marge brute très faible : {pct:.1f}%"


def _score_operating_margin(margin: Optional[float]) -> tuple[float, str]:
    """Scoring marge opérationnelle."""
    if margin is None:
        return 50.0, "Marge opérationnelle indisponible"
    pct = margin * 100
    if pct >= 20:
        return 100.0, f"Marge opérationnelle excellente : {pct:.1f}%"
    if pct >= 12:
        return 80.0, f"Marge opérationnelle solide : {pct:.1f}%"
    if pct >= 6:
        return 60.0, f"Marge opérationnelle correcte : {pct:.1f}%"
    if pct >= 2:
        return 35.0, f"Marge opérationnelle faible : {pct:.1f}%"
    return 10.0, f"Marge opérationnelle négative ou nulle : {pct:.1f}%"


def _score_net_margin(margin: Optional[float]) -> tuple[float, str]:
    """Scoring marge nette."""
    if margin is None:
        return 50.0, "Marge nette indisponible"
    pct = margin * 100
    if pct >= 15:
        return 100.0, f"Marge nette excellente : {pct:.1f}%"
    if pct >= 8:
        return 80.0, f"Marge nette solide : {pct:.1f}%"
    if pct >= 4:
        return 60.0, f"Marge nette correcte : {pct:.1f}%"
    if pct >= 0:
        return 35.0, f"Marge nette faible : {pct:.1f}%"
    return 5.0, f"Marge nette négative : {pct:.1f}%"


def _score_roe(roe: Optional[float]) -> tuple[float, str]:
    """Scoring ROE."""
    if roe is None:
        return 50.0, "ROE indisponible"
    pct = roe * 100
    if pct >= 20:
        return 100.0, f"ROE excellent : {pct:.1f}%"
    if pct >= 14:
        return 80.0, f"ROE solide : {pct:.1f}%"
    if pct >= 8:
        return 60.0, f"ROE modéré : {pct:.1f}%"
    if pct >= 0:
        return 30.0, f"ROE faible : {pct:.1f}%"
    return 5.0, f"ROE négatif : {pct:.1f}%"


def _score_roa(roa: Optional[float]) -> tuple[float, str]:
    """Scoring ROA."""
    if roa is None:
        return 50.0, "ROA indisponible"
    pct = roa * 100
    if pct >= 10:
        return 100.0, f"ROA excellent : {pct:.1f}%"
    if pct >= 6:
        return 80.0, f"ROA solide : {pct:.1f}%"
    if pct >= 3:
        return 60.0, f"ROA modéré : {pct:.1f}%"
    if pct >= 0:
        return 35.0, f"ROA faible : {pct:.1f}%"
    return 5.0, f"ROA négatif : {pct:.1f}%"


def _score_per(per: Optional[float]) -> tuple[float, str]:
    """Scoring PER (valorisation côté rentabilité — pénalise le surachat)."""
    if per is None or per <= 0:
        return 50.0, "PER indisponible ou non significatif"
    if per < 10:
        return 90.0, f"PER très bas (action décotée) : {per:.1f}x"
    if per < 15:
        return 80.0, f"PER attractif : {per:.1f}x"
    if per < 20:
        return 65.0, f"PER raisonnable : {per:.1f}x"
    if per < 30:
        return 45.0, f"PER élevé : {per:.1f}x"
    return 20.0, f"PER très élevé (action chère) : {per:.1f}x"


# Pondérations internes des critères de rentabilité
_WEIGHTS = {
    "cagr_revenue": 0.20,
    "cagr_eps": 0.15,
    "cagr_dividend": 0.08,
    "gross_margin": 0.10,
    "operating_margin": 0.15,
    "net_margin": 0.12,
    "roe": 0.10,
    "roa": 0.05,
    "per": 0.05,
}


def _interpretation(score: float) -> str:
    if score >= 80:
        return "Entreprise très rentable avec une dynamique de croissance forte."
    if score >= 65:
        return "Bonne rentabilité, quelques points d'amélioration possibles."
    if score >= 50:
        return "Rentabilité correcte mais perfectible sur certains axes."
    if score >= 35:
        return "Rentabilité fragile — surveiller l'évolution des marges."
    return "Rentabilité insuffisante — situation préoccupante."


def compute(data: dict) -> RentabiliteScore:
    """Calcule le score de rentabilité à partir des données scrapées."""
    m = RentabiliteMetrics(
        revenue_cagr_10y=data.get("revenue_cagr_10y"),
        eps_cagr_10y=data.get("eps_cagr_10y"),
        dividend_cagr_10y=data.get("dividend_cagr_10y"),
        gross_margin=data.get("gross_margin"),
        operating_margin=data.get("operating_margin"),
        net_margin=data.get("net_margin"),
        roe=data.get("roe"),
        roa=data.get("roa"),
        per=data.get("per"),
        revenues=data.get("revenues"),
        net_incomes=data.get("net_incomes"),
        gross_profits=data.get("gross_profits"),
        eps_history=data.get("eps_history"),
        dividend_history=data.get("dividend_history"),
        years=data.get("years"),
    )

    scores_and_msgs = {
        "cagr_revenue": _score_cagr_revenue(m.revenue_cagr_10y),
        "cagr_eps": _score_cagr_eps(m.eps_cagr_10y),
        "cagr_dividend": _score_cagr_dividend(m.dividend_cagr_10y),
        "gross_margin": _score_gross_margin(m.gross_margin),
        "operating_margin": _score_operating_margin(m.operating_margin),
        "net_margin": _score_net_margin(m.net_margin),
        "roe": _score_roe(m.roe),
        "roa": _score_roa(m.roa),
        "per": _score_per(m.per),
    }

    weighted_score = sum(
        scores_and_msgs[k][0] * _WEIGHTS[k] for k in _WEIGHTS
    )

    strengths = [msg for k, (s, msg) in scores_and_msgs.items() if s >= 70]
    weaknesses = [msg for k, (s, msg) in scores_and_msgs.items() if s < 45]

    return RentabiliteScore(
        score=round(weighted_score, 1),
        metrics=m,
        strengths=strengths,
        weaknesses=weaknesses,
        interpretation=_interpretation(weighted_score),
    )
