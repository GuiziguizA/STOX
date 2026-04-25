"""
Module d'analyse des Flux de Trésorerie (poids 20% du score global).

Critères scorés :
- Free Cash Flow (FCF) absolu et tendance
- Taux de conversion résultat → cash (FCF / Résultat net)
- FCF yield implicite (FCF / Market Cap)
- Couverture de la dette par le FCF
- Régularité / croissance du FCF sur 5 ans
"""
from typing import Optional

from models.schemas import FluxMetrics, FluxScore


def _cagr(values: list) -> Optional[float]:
    clean = [v for v in values if v is not None and v > 0]
    if len(clean) < 2:
        return None
    n = len(clean) - 1
    try:
        return (clean[-1] / clean[0]) ** (1 / n) - 1
    except (ZeroDivisionError, ValueError):
        return None


def _score_fcf(fcf: Optional[float], revenue: Optional[float]) -> tuple[float, str]:
    """FCF positif et significatif par rapport au CA."""
    if fcf is None:
        return 50.0, "FCF indisponible"
    if fcf < 0:
        return 10.0, f"FCF négatif : {fcf:,.0f} — consommation de trésorerie"
    if revenue and revenue > 0:
        pct = fcf / revenue * 100
        if pct >= 15:
            return 100.0, f"FCF très élevé : {pct:.1f}% du CA ({fcf:,.0f})"
        if pct >= 8:
            return 80.0, f"FCF solide : {pct:.1f}% du CA"
        if pct >= 4:
            return 60.0, f"FCF correct : {pct:.1f}% du CA"
        return 40.0, f"FCF faible vs CA : {pct:.1f}%"
    return 55.0, f"FCF positif : {fcf:,.0f}"


def _score_cash_conversion(ratio: Optional[float]) -> tuple[float, str]:
    """
    Conversion résultat/cash = FCF / Résultat net.
    Un ratio > 1 indique une meilleure qualité des bénéfices que le comptable.
    """
    if ratio is None:
        return 50.0, "Taux de conversion résultat/cash indisponible"
    if ratio > 1.2:
        return 100.0, f"Excellente qualité des bénéfices : FCF/Résultat = {ratio:.2f}x"
    if ratio > 0.8:
        return 80.0, f"Bonne conversion résultat → cash : {ratio:.2f}x"
    if ratio > 0.5:
        return 55.0, f"Conversion résultat/cash correcte : {ratio:.2f}x"
    if ratio > 0:
        return 30.0, f"Faible conversion résultat/cash : {ratio:.2f}x"
    return 5.0, f"Bénéfices comptables non convertis en cash : {ratio:.2f}x"


def _score_debt_coverage(ratio: Optional[float]) -> tuple[float, str]:
    """Couverture de la dette nette par le FCF."""
    if ratio is None:
        return 60.0, "Couverture dette/FCF indisponible (pas de dette ou FCF)"
    if ratio < 0:
        # Dette négative (trésorerie excédentaire) ou FCF négatif
        if ratio < -0.1:
            return 10.0, f"FCF négatif — impossible de couvrir la dette : {ratio:.2f}x"
        return 100.0, "Trésorerie nette positive — aucune dette nette"
    if ratio > 0.5:
        return 100.0, f"FCF couvre > 50% de la dette nette chaque année : {ratio:.2f}x"
    if ratio > 0.25:
        return 80.0, f"Bonne couverture dette par FCF : {ratio:.2f}x"
    if ratio > 0.10:
        return 55.0, f"Couverture dette/FCF correcte : {ratio:.2f}x"
    return 25.0, f"Faible couverture de la dette par le FCF : {ratio:.2f}x"


def _score_fcf_trend(fcf_history: Optional[list]) -> tuple[float, str]:
    """Tendance FCF sur 5 ans — CAGR et régularité."""
    if not fcf_history or len(fcf_history) < 2:
        return 50.0, "Historique FCF insuffisant"

    # Régularité : combien d'années positives
    positives = sum(1 for v in fcf_history if v is not None and v > 0)
    total = sum(1 for v in fcf_history if v is not None)
    if total == 0:
        return 50.0, "Historique FCF vide"

    positive_ratio = positives / total
    cagr = _cagr(fcf_history)

    if cagr is not None and cagr >= 0.10 and positive_ratio >= 0.8:
        return 100.0, f"FCF en forte croissance ({cagr*100:.1f}%/an) et régulier ({positives}/{total} années positives)"
    if cagr is not None and cagr >= 0.05 and positive_ratio >= 0.6:
        return 75.0, f"FCF en croissance ({cagr*100:.1f}%/an), {positives}/{total} années positives"
    if positive_ratio >= 0.8:
        return 65.0, f"FCF stable et régulier ({positives}/{total} années positives)"
    if positive_ratio >= 0.5:
        return 40.0, f"FCF irrégulier : {positives}/{total} années positives"
    return 15.0, f"FCF majoritairement négatif : seulement {positives}/{total} années positives"


def _score_fcf_yield(fcf_yield: Optional[float]) -> tuple[float, str]:
    """FCF yield = FCF / Market Cap."""
    if fcf_yield is None:
        return 50.0, "FCF yield indisponible"
    pct = fcf_yield * 100
    if pct >= 7:
        return 100.0, f"FCF yield excellent (zone Solde) : {pct:.1f}%"
    if pct >= 5.5:
        return 80.0, f"FCF yield attractif : {pct:.1f}%"
    if pct >= 4.5:
        return 65.0, f"FCF yield fair value : {pct:.1f}%"
    if pct >= 3:
        return 45.0, f"FCF yield faible : {pct:.1f}%"
    if pct >= 0:
        return 25.0, f"FCF yield très faible : {pct:.1f}%"
    return 10.0, f"FCF yield négatif : {pct:.1f}%"


_WEIGHTS = {
    "fcf": 0.30,
    "cash_conversion": 0.25,
    "debt_coverage": 0.20,
    "fcf_trend": 0.15,
    "fcf_yield": 0.10,
}


def _interpretation(score: float) -> str:
    if score >= 80:
        return "Génération de trésorerie excellente — bénéfices de haute qualité, cash abondant."
    if score >= 65:
        return "Bonne génération de cash avec une conversion solide du résultat."
    if score >= 50:
        return "Cash flow correct mais avec des marges de progression."
    if score >= 35:
        return "Flux de trésorerie fragiles — surveiller la conversion résultat/cash."
    return "Mauvaise génération de trésorerie — risque de tension de liquidité."


def compute(data: dict) -> FluxScore:
    fcf = data.get("fcf")
    fcf_per_share = data.get("fcf_per_share")
    fcf_history = data.get("fcf_history") or []
    operating_cf = data.get("operating_cf")
    capex = data.get("capex")
    cash_conversion = data.get("cash_conversion")
    debt_coverage_fcf = data.get("debt_coverage_fcf")
    fcf_yield = data.get("fcf_yield")
    operating_cf_history = data.get("operating_cf_history") or []
    latest_revenue = data.get("latest_revenue")

    m = FluxMetrics(
        operating_cash_flow=operating_cf,
        capex=capex,
        free_cash_flow=fcf,
        fcf_per_share=fcf_per_share,
        cash_conversion_ratio=cash_conversion,
        debt_coverage_by_fcf=debt_coverage_fcf,
        fcf_history=fcf_history if fcf_history else None,
        operating_cf_history=operating_cf_history if operating_cf_history else None,
    )

    scores_and_msgs = {
        "fcf": _score_fcf(fcf, latest_revenue),
        "cash_conversion": _score_cash_conversion(cash_conversion),
        "debt_coverage": _score_debt_coverage(debt_coverage_fcf),
        "fcf_trend": _score_fcf_trend(fcf_history),
        "fcf_yield": _score_fcf_yield(fcf_yield),
    }

    weighted_score = sum(
        scores_and_msgs[k][0] * _WEIGHTS[k] for k in _WEIGHTS
    )

    strengths = [msg for k, (s, msg) in scores_and_msgs.items() if s >= 70]
    weaknesses = [msg for k, (s, msg) in scores_and_msgs.items() if s < 45]

    return FluxScore(
        score=round(weighted_score, 1),
        metrics=m,
        strengths=strengths,
        weaknesses=weaknesses,
        interpretation=_interpretation(weighted_score),
    )
