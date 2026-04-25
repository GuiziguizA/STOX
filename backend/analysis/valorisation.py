"""
Module de Valorisation Boursière (poids 25% du score global).

4 méthodes croisées selon le framework analyse_entreprise :

1. PER :  Prix cible = PER cible × BNA
   - Solde    : PER < 13.5x
   - Attractif: 13.5 – 15.7x
   - FairValue: 15.7 – 18x
   - Cher     : > 18x

2. Rendement dividende :
   - Solde    : yield > 6%
   - Attractif: 5 – 6%
   - FairValue: 4.5 – 5%
   - Cher     : < 4.5%

3. FCF Yield :
   - Solde    : > 7%
   - Attractif: 5.5 – 7%
   - FairValue: 4.5 – 5.5%
   - Cher     : < 4.5%

4. DCF simplifié :
   - FCF actuel projeté sur 5 ans (taux de croissance estimé),
     puis croissance terminale 2%,
     actualisé au WACC estimé à partir du beta.
"""
from typing import Optional

from models.schemas import (
    ValuationMethod,
    ValuationZoneResult,
    ValorisationMetrics,
    ValorisationScore,
)

_ZONE_SOLDE = "Solde"
_ZONE_ATTRACTIF = "Attractif"
_ZONE_FAIR_VALUE = "Fair Value"
_ZONE_CHER = "Cher"
_ZONE_UNKNOWN = "Indéterminée"

# PER cibles par zone
_PER_SOLDE = 12.0
_PER_ATTRACTIF = 15.0
_PER_FAIR_VALUE = 18.0
_PER_CHER = 22.0

# Rendement dividende cible par zone (en %)
_DIV_YIELD_SOLDE = 6.0
_DIV_YIELD_ATTRACTIF = 5.0
_DIV_YIELD_FAIR_VALUE = 4.5
_DIV_YIELD_CHER = 4.0

# FCF Yield cibles par zone (en %)
_FCF_YIELD_SOLDE = 7.0
_FCF_YIELD_ATTRACTIF = 5.5
_FCF_YIELD_FAIR_VALUE = 4.5
_FCF_YIELD_CHER = 3.5


def _zone_per(per: Optional[float]) -> str:
    if per is None or per <= 0:
        return _ZONE_UNKNOWN
    if per < 13.5:
        return _ZONE_SOLDE
    if per < 15.7:
        return _ZONE_ATTRACTIF
    if per < 18.0:
        return _ZONE_FAIR_VALUE
    return _ZONE_CHER


def _zone_div_yield(yield_pct: Optional[float]) -> str:
    """yield_pct en décimal (0.05 = 5%)."""
    if yield_pct is None:
        return _ZONE_UNKNOWN
    pct = yield_pct * 100
    if pct >= _DIV_YIELD_SOLDE:
        return _ZONE_SOLDE
    if pct >= _DIV_YIELD_ATTRACTIF:
        return _ZONE_ATTRACTIF
    if pct >= _DIV_YIELD_FAIR_VALUE:
        return _ZONE_FAIR_VALUE
    return _ZONE_CHER


def _zone_fcf_yield(yield_pct: Optional[float]) -> str:
    """yield_pct en décimal (0.05 = 5%)."""
    if yield_pct is None:
        return _ZONE_UNKNOWN
    pct = yield_pct * 100
    if pct > _FCF_YIELD_SOLDE:
        return _ZONE_SOLDE
    if pct > _FCF_YIELD_ATTRACTIF:
        return _ZONE_ATTRACTIF
    if pct > _FCF_YIELD_FAIR_VALUE:
        return _ZONE_FAIR_VALUE
    return _ZONE_CHER


def _zone_dcf(current_price: Optional[float], dcf_value: Optional[float]) -> str:
    if current_price is None or dcf_value is None or dcf_value <= 0:
        return _ZONE_UNKNOWN
    ratio = current_price / dcf_value
    if ratio < 0.75:
        return _ZONE_SOLDE
    if ratio < 0.90:
        return _ZONE_ATTRACTIF
    if ratio <= 1.10:
        return _ZONE_FAIR_VALUE
    return _ZONE_CHER


_ZONE_ORDER = {_ZONE_SOLDE: 0, _ZONE_ATTRACTIF: 1, _ZONE_FAIR_VALUE: 2, _ZONE_CHER: 3}


def _consensus_zone(zones: list[str]) -> str:
    known = [z for z in zones if z != _ZONE_UNKNOWN]
    if not known:
        return _ZONE_UNKNOWN
    # Vote par majorité simple, en cas d'égalité on prend la zone médiane
    from collections import Counter
    counts = Counter(known)
    if len(counts) == 1:
        return known[0]
    # Retourner la zone avec le plus de votes, ou la plus conservatrice
    max_count = max(counts.values())
    candidates = [z for z, c in counts.items() if c == max_count]
    # Parmi les ex-aequo, retourner la moins favorable (la plus chère → plus prudent)
    return max(candidates, key=lambda z: _ZONE_ORDER.get(z, 2))


def _score_zone(zone: str) -> float:
    """Score de valorisation en fonction de la zone consensus."""
    return {
        _ZONE_SOLDE: 100.0,
        _ZONE_ATTRACTIF: 78.0,
        _ZONE_FAIR_VALUE: 55.0,
        _ZONE_CHER: 20.0,
        _ZONE_UNKNOWN: 50.0,
    }.get(zone, 50.0)


def _estimate_wacc(beta: Optional[float]) -> float:
    """WACC estimé simplifié basé sur le beta."""
    risk_free = 0.04   # taux sans risque ≈ 4% (OAT 10 ans)
    market_premium = 0.055  # prime de risque marché ≈ 5.5%
    b = beta if beta and 0 < beta < 5 else 1.0
    return risk_free + b * market_premium


def _dcf_value(
    fcf: Optional[float],
    shares: Optional[float],
    revenue_cagr: Optional[float],
    beta: Optional[float],
) -> Optional[float]:
    """
    DCF simplifié :
    - Phase 1 : 5 ans au taux de croissance estimé (min CAGR rev, max 15%)
    - Phase 2 : croissance terminale 2%
    - Actualisation au WACC
    """
    if fcf is None or shares is None or shares <= 0 or fcf <= 0:
        return None

    wacc = _estimate_wacc(beta)
    # Taux de croissance phase 1 — proxy = CAGR CA plafonné
    growth = max(0.0, min(revenue_cagr or 0.05, 0.15))

    # VAN Phase 1
    pv = 0.0
    current_fcf = fcf
    for year in range(1, 6):
        current_fcf *= (1 + growth)
        pv += current_fcf / (1 + wacc) ** year

    # Valeur terminale (Gordon-Shapiro)
    terminal_growth = 0.02
    if wacc <= terminal_growth:
        return None
    terminal_fcf = current_fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv += terminal_value / (1 + wacc) ** 5

    return pv / shares


def _price_targets_per(eps: Optional[float]) -> dict:
    if eps is None or eps <= 0:
        return {}
    return {
        _ZONE_SOLDE: eps * _PER_SOLDE,
        _ZONE_ATTRACTIF: eps * _PER_ATTRACTIF,
        _ZONE_FAIR_VALUE: eps * _PER_FAIR_VALUE,
        _ZONE_CHER: eps * _PER_CHER,
    }


def _price_targets_div(dps: Optional[float]) -> dict:
    if dps is None or dps <= 0:
        return {}
    return {
        _ZONE_SOLDE: dps / (_DIV_YIELD_SOLDE / 100),
        _ZONE_ATTRACTIF: dps / (_DIV_YIELD_ATTRACTIF / 100),
        _ZONE_FAIR_VALUE: dps / (_DIV_YIELD_FAIR_VALUE / 100),
        _ZONE_CHER: dps / (_DIV_YIELD_CHER / 100),
    }


def _price_targets_fcf(fcf_ps: Optional[float]) -> dict:
    if fcf_ps is None or fcf_ps <= 0:
        return {}
    return {
        _ZONE_SOLDE: fcf_ps / (_FCF_YIELD_SOLDE / 100),
        _ZONE_ATTRACTIF: fcf_ps / (_FCF_YIELD_ATTRACTIF / 100),
        _ZONE_FAIR_VALUE: fcf_ps / (_FCF_YIELD_FAIR_VALUE / 100),
        _ZONE_CHER: fcf_ps / (_FCF_YIELD_CHER / 100),
    }


def _interpretation(score: float, zone: str) -> str:
    base = {
        _ZONE_SOLDE: "Action en zone SOLDE — opportunité d'achat avec forte marge de sécurité.",
        _ZONE_ATTRACTIF: "Action en zone ATTRACTIF — valorisation raisonnable, point d'entrée favorable.",
        _ZONE_FAIR_VALUE: "Action à sa FAIR VALUE — prix juste, peu de marge de sécurité.",
        _ZONE_CHER: "Action en zone CHER — prime de valorisation élevée, risque de correction.",
        _ZONE_UNKNOWN: "Zone de valorisation indéterminée — données insuffisantes.",
    }.get(zone, "Zone indéterminée.")
    return base


def compute(data: dict) -> ValorisationScore:
    current_price = data.get("current_price")
    eps_ttm = data.get("eps_ttm")
    per = data.get("per")
    dps = data.get("dividend_per_share")
    div_yield = data.get("dividend_yield")
    fcf_per_share = data.get("fcf_per_share")
    fcf_yield = data.get("fcf_yield")
    beta = data.get("beta")
    market_cap = data.get("market_cap")
    fcf = data.get("fcf")
    shares = data.get("shares_outstanding")
    revenue_cagr = data.get("revenue_cagr_10y")

    # WACC
    wacc = _estimate_wacc(beta)

    # DCF
    dcf_val = _dcf_value(fcf, shares, revenue_cagr, beta)

    # Zones par méthode
    zone_per = _zone_per(per)
    zone_div = _zone_div_yield(div_yield)
    zone_fcf = _zone_fcf_yield(fcf_yield)
    zone_dcf = _zone_dcf(current_price, dcf_val)

    # Méthodes détaillées
    per_targets = _price_targets_per(eps_ttm)
    div_targets = _price_targets_div(dps)
    fcf_targets = _price_targets_fcf(fcf_per_share)

    methods = [
        ValuationMethod(
            name="PER",
            target_solde=per_targets.get(_ZONE_SOLDE),
            target_attractif=per_targets.get(_ZONE_ATTRACTIF),
            target_fair_value=per_targets.get(_ZONE_FAIR_VALUE),
            target_cher=per_targets.get(_ZONE_CHER),
            current_metric=per,
            zone=zone_per,
        ),
        ValuationMethod(
            name="Rendement dividende",
            target_solde=div_targets.get(_ZONE_SOLDE),
            target_attractif=div_targets.get(_ZONE_ATTRACTIF),
            target_fair_value=div_targets.get(_ZONE_FAIR_VALUE),
            target_cher=div_targets.get(_ZONE_CHER),
            current_metric=div_yield * 100 if div_yield else None,
            zone=zone_div,
        ),
        ValuationMethod(
            name="FCF Yield",
            target_solde=fcf_targets.get(_ZONE_SOLDE),
            target_attractif=fcf_targets.get(_ZONE_ATTRACTIF),
            target_fair_value=fcf_targets.get(_ZONE_FAIR_VALUE),
            target_cher=fcf_targets.get(_ZONE_CHER),
            current_metric=fcf_yield * 100 if fcf_yield else None,
            zone=zone_fcf,
        ),
        ValuationMethod(
            name="DCF simplifié",
            target_fair_value=dcf_val,
            current_metric=current_price,
            zone=zone_dcf,
        ),
    ]

    # Zone consensus (toutes méthodes)
    all_zones = [zone_per, zone_div, zone_fcf, zone_dcf]
    consensus_zone = _consensus_zone(all_zones)

    # Fair value estimée : moyenne des targets Fair Value disponibles
    fv_estimates = []
    if per_targets.get(_ZONE_FAIR_VALUE):
        fv_estimates.append(per_targets[_ZONE_FAIR_VALUE])
    if div_targets.get(_ZONE_FAIR_VALUE):
        fv_estimates.append(div_targets[_ZONE_FAIR_VALUE])
    if fcf_targets.get(_ZONE_FAIR_VALUE):
        fv_estimates.append(fcf_targets[_ZONE_FAIR_VALUE])
    if dcf_val:
        fv_estimates.append(dcf_val)
    fair_value_estimate = sum(fv_estimates) / len(fv_estimates) if fv_estimates else None

    # Marge de sécurité
    safety_margin = None
    if fair_value_estimate and current_price and current_price > 0:
        safety_margin = (fair_value_estimate - current_price) / current_price * 100

    # Fourchettes de prix par zone (moyenne des méthodes disponibles)
    def avg_zone_price(zone_key: str) -> Optional[float]:
        vals = []
        if per_targets.get(zone_key):
            vals.append(per_targets[zone_key])
        if div_targets.get(zone_key):
            vals.append(div_targets[zone_key])
        if fcf_targets.get(zone_key):
            vals.append(fcf_targets[zone_key])
        return sum(vals) / len(vals) if vals else None

    solde_avg = avg_zone_price(_ZONE_SOLDE)
    attractif_avg = avg_zone_price(_ZONE_ATTRACTIF)
    fv_avg = avg_zone_price(_ZONE_FAIR_VALUE)
    cher_avg = avg_zone_price(_ZONE_CHER)

    zone_result = ValuationZoneResult(
        zone=consensus_zone,
        price_range_solde=(0, solde_avg) if solde_avg else None,
        price_range_attractif=(solde_avg, attractif_avg) if solde_avg and attractif_avg else None,
        price_range_fair_value=(attractif_avg, fv_avg) if attractif_avg and fv_avg else None,
        price_range_cher=(fv_avg, None) if fv_avg else None,
        current_price=current_price,
        fair_value_estimate=fair_value_estimate,
        safety_margin_pct=safety_margin,
    )

    score = _score_zone(consensus_zone)

    # Modulation du score selon la marge de sécurité
    if safety_margin is not None and consensus_zone == _ZONE_FAIR_VALUE:
        if safety_margin > 10:
            score = min(score + 10, 100)
        elif safety_margin < -10:
            score = max(score - 10, 0)

    metrics = ValorisationMetrics(
        current_price=current_price,
        per_current=per,
        eps_ttm=eps_ttm,
        dividend_per_share=dps,
        dividend_yield=div_yield,
        fcf_per_share=fcf_per_share,
        fcf_yield=fcf_yield,
        beta=beta,
        market_cap=market_cap,
        wacc=wacc,
        dcf_value=dcf_val,
    )

    # Forces et faiblesses
    strengths, weaknesses = [], []
    zone_scores = {zone_per: "PER", zone_div: "Dividende", zone_fcf: "FCF Yield", zone_dcf: "DCF"}
    for z, method_name in zone_scores.items():
        if z in (_ZONE_SOLDE, _ZONE_ATTRACTIF):
            strengths.append(f"Méthode {method_name} : zone {z}")
        elif z == _ZONE_CHER:
            weaknesses.append(f"Méthode {method_name} : zone {z} — valorisation élevée")
    if safety_margin is not None:
        if safety_margin > 15:
            strengths.append(f"Marge de sécurité de {safety_margin:.1f}% par rapport à la fair value")
        elif safety_margin < -10:
            weaknesses.append(f"Action surévaluée de {abs(safety_margin):.1f}% vs fair value")

    return ValorisationScore(
        score=round(score, 1),
        metrics=metrics,
        methods=methods,
        zone_result=zone_result,
        strengths=strengths,
        weaknesses=weaknesses,
        interpretation=_interpretation(score, consensus_zone),
    )
