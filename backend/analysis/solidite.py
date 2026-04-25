"""
Module d'analyse de la Solidité Financière (poids 25% du score global).

Critères scorés :
- Dette nette / EBITDA
- Dette nette / CAF
- Gearing (endettement / capitaux propres)
- Autonomie financière
- Fonds de roulement
- BFR
- Liquidité générale
- Liquidité immédiate
- Couverture des intérêts
"""
from typing import Optional

from models.schemas import SoliditeMetrics, SoliditeScore


def _score_net_debt_ebitda(ratio: Optional[float]) -> tuple[float, str]:
    """Dette nette / EBITDA — seuil critique ≥ 3x."""
    if ratio is None:
        return 50.0, "Ratio Dette nette/EBITDA indisponible"
    if ratio < 0:
        return 100.0, f"Trésorerie nette positive (Dette nette/EBITDA = {ratio:.2f}x)"
    if ratio < 1:
        return 95.0, f"Endettement quasi nul : Dette nette/EBITDA = {ratio:.2f}x"
    if ratio < 2:
        return 80.0, f"Endettement faible : Dette nette/EBITDA = {ratio:.2f}x"
    if ratio < 3:
        return 60.0, f"Endettement modéré : Dette nette/EBITDA = {ratio:.2f}x"
    if ratio < 5:
        return 30.0, f"Endettement élevé : Dette nette/EBITDA = {ratio:.2f}x"
    return 10.0, f"Endettement excessif : Dette nette/EBITDA = {ratio:.2f}x"


def _score_gearing(gearing: Optional[float]) -> tuple[float, str]:
    """Gearing = dette nette / capitaux propres."""
    if gearing is None:
        return 50.0, "Gearing indisponible"
    pct = gearing * 100
    if gearing < 0:
        return 100.0, f"Gearing négatif — excédent de trésorerie : {pct:.0f}%"
    if gearing < 0.30:
        return 90.0, f"Gearing très faible : {pct:.0f}%"
    if gearing < 0.60:
        return 75.0, f"Gearing faible : {pct:.0f}%"
    if gearing < 1.0:
        return 55.0, f"Gearing modéré : {pct:.0f}%"
    if gearing < 1.5:
        return 30.0, f"Gearing élevé : {pct:.0f}%"
    return 10.0, f"Gearing très élevé : {pct:.0f}%"


def _score_financial_autonomy(ratio: Optional[float]) -> tuple[float, str]:
    """Autonomie financière = capitaux propres / total actif."""
    if ratio is None:
        return 50.0, "Autonomie financière indisponible"
    pct = ratio * 100
    if pct >= 50:
        return 100.0, f"Excellente autonomie financière : {pct:.0f}% d'actifs financés par fonds propres"
    if pct >= 35:
        return 80.0, f"Bonne autonomie financière : {pct:.0f}%"
    if pct >= 20:
        return 55.0, f"Autonomie financière correcte : {pct:.0f}%"
    if pct >= 10:
        return 30.0, f"Autonomie financière faible : {pct:.0f}%"
    return 10.0, f"Dépendance forte aux dettes : {pct:.0f}%"


def _score_current_ratio(ratio: Optional[float]) -> tuple[float, str]:
    """Liquidité générale — idéalement > 1.5."""
    if ratio is None:
        return 50.0, "Ratio de liquidité générale indisponible"
    if ratio >= 2.0:
        return 100.0, f"Liquidité générale excellente : {ratio:.2f}x"
    if ratio >= 1.5:
        return 80.0, f"Liquidité générale bonne : {ratio:.2f}x"
    if ratio >= 1.0:
        return 55.0, f"Liquidité générale correcte : {ratio:.2f}x"
    return 20.0, f"Liquidité générale insuffisante : {ratio:.2f}x (< 1)"


def _score_quick_ratio(ratio: Optional[float]) -> tuple[float, str]:
    """Liquidité immédiate (hors stocks)."""
    if ratio is None:
        return 50.0, "Ratio de liquidité immédiate indisponible"
    if ratio >= 1.5:
        return 100.0, f"Liquidité immédiate excellente : {ratio:.2f}x"
    if ratio >= 1.0:
        return 75.0, f"Liquidité immédiate bonne : {ratio:.2f}x"
    if ratio >= 0.7:
        return 50.0, f"Liquidité immédiate correcte : {ratio:.2f}x"
    return 20.0, f"Liquidité immédiate faible : {ratio:.2f}x"


def _score_interest_coverage(ratio: Optional[float]) -> tuple[float, str]:
    """Couverture des intérêts = EBIT / charges financières."""
    if ratio is None:
        return 60.0, "Couverture des intérêts indisponible (pas de dette ou données insuffisantes)"
    if ratio >= 10:
        return 100.0, f"Couverture des intérêts excellente : {ratio:.1f}x"
    if ratio >= 5:
        return 80.0, f"Couverture des intérêts solide : {ratio:.1f}x"
    if ratio >= 3:
        return 60.0, f"Couverture des intérêts correcte : {ratio:.1f}x"
    if ratio >= 1.5:
        return 35.0, f"Couverture des intérêts faible : {ratio:.1f}x"
    return 10.0, f"Couverture des intérêts insuffisante — risque de défaut : {ratio:.1f}x"


def _score_debt_repayment(years: Optional[float]) -> tuple[float, str]:
    """Nombre d'années pour rembourser la dette nette avec le CAF."""
    if years is None:
        return 60.0, "Durée de remboursement indisponible"
    if years < 0:
        return 100.0, "Trésorerie nette — pas de dette à rembourser"
    if years < 2:
        return 95.0, f"Dette remboursable en {years:.1f} an(s)"
    if years < 4:
        return 75.0, f"Dette remboursable en {years:.1f} ans"
    if years < 6:
        return 50.0, f"Dette remboursable en {years:.1f} ans"
    if years < 10:
        return 25.0, f"Dette remboursable en {years:.1f} ans — charge lourde"
    return 5.0, f"Durée de remboursement très longue : {years:.1f} ans"


def _risk_level(score: float) -> str:
    if score >= 75:
        return "Faible"
    if score >= 55:
        return "Modéré"
    if score >= 35:
        return "Élevé"
    return "Très élevé"


def _interpretation(score: float) -> str:
    if score >= 80:
        return "Bilan très solide, faible dépendance à la dette, excellente solvabilité."
    if score >= 65:
        return "Structure financière saine avec quelques points de vigilance."
    if score >= 50:
        return "Solidité financière correcte mais endettement à surveiller."
    if score >= 35:
        return "Fragilité financière — la dette représente un risque non négligeable."
    return "Situation financière préoccupante — risque élevé de difficultés."


_WEIGHTS = {
    "net_debt_ebitda": 0.25,
    "gearing": 0.15,
    "financial_autonomy": 0.15,
    "current_ratio": 0.15,
    "quick_ratio": 0.10,
    "interest_coverage": 0.12,
    "debt_repayment": 0.08,
}


def compute(data: dict) -> SoliditeScore:
    m = SoliditeMetrics(
        net_debt=data.get("net_debt"),
        net_debt_ebitda=data.get("net_debt_ebitda"),
        net_debt_caf=data.get("net_debt_caf"),
        gearing=data.get("gearing"),
        financial_autonomy=data.get("financial_autonomy"),
        working_capital=data.get("working_capital"),
        wcr=data.get("wcr"),
        net_cash_position=data.get("net_cash_position"),
        current_ratio=data.get("current_ratio"),
        quick_ratio=data.get("quick_ratio"),
        interest_coverage=data.get("interest_coverage"),
        debt_repayment_years=data.get("debt_repayment_years"),
    )

    scores_and_msgs = {
        "net_debt_ebitda": _score_net_debt_ebitda(m.net_debt_ebitda),
        "gearing": _score_gearing(m.gearing),
        "financial_autonomy": _score_financial_autonomy(m.financial_autonomy),
        "current_ratio": _score_current_ratio(m.current_ratio),
        "quick_ratio": _score_quick_ratio(m.quick_ratio),
        "interest_coverage": _score_interest_coverage(m.interest_coverage),
        "debt_repayment": _score_debt_repayment(m.debt_repayment_years),
    }

    weighted_score = sum(
        scores_and_msgs[k][0] * _WEIGHTS[k] for k in _WEIGHTS
    )

    strengths = [msg for k, (s, msg) in scores_and_msgs.items() if s >= 70]
    weaknesses = [msg for k, (s, msg) in scores_and_msgs.items() if s < 45]

    return SoliditeScore(
        score=round(weighted_score, 1),
        metrics=m,
        risk_level=_risk_level(weighted_score),
        strengths=strengths,
        weaknesses=weaknesses,
        interpretation=_interpretation(weighted_score),
    )
