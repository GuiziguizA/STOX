"""
Pydantic schemas for financial analysis API responses.
"""
from typing import Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Rentabilité (30%)
# ---------------------------------------------------------------------------

class RentabiliteMetrics(BaseModel):
    revenue_cagr_10y: Optional[float] = None          # % CAGR CA sur 10 ans
    eps_cagr_10y: Optional[float] = None               # % CAGR BNA sur 10 ans
    dividend_cagr_10y: Optional[float] = None          # % CAGR dividende sur 10 ans
    gross_margin: Optional[float] = None               # % marge brute (dernière année)
    operating_margin: Optional[float] = None           # % marge opérationnelle
    net_margin: Optional[float] = None                 # % marge nette
    roe: Optional[float] = None                        # Return on Equity %
    roa: Optional[float] = None                        # Return on Assets %
    per: Optional[float] = None                        # Price Earnings Ratio
    revenues: Optional[list[Optional[float]]] = None    # CA sur 10 ans (chronologique)
    net_incomes: Optional[list[Optional[float]]] = None # Résultat net sur 10 ans
    gross_profits: Optional[list[Optional[float]]] = None  # Résultat brut sur 10 ans
    eps_history: Optional[list[Optional[float]]] = None # BNA sur 10 ans
    dividend_history: Optional[list[Optional[float]]] = None  # Dividendes sur 10 ans
    years: Optional[list[int]] = None                  # Années associées


class RentabiliteScore(BaseModel):
    score: float                   # /100
    metrics: RentabiliteMetrics
    strengths: list[str]
    weaknesses: list[str]
    interpretation: str


# ---------------------------------------------------------------------------
# Solidité financière (25%)
# ---------------------------------------------------------------------------

class SoliditeMetrics(BaseModel):
    net_debt: Optional[float] = None                   # Dette nette (M€/$)
    net_debt_ebitda: Optional[float] = None            # Dette nette / EBITDA
    net_debt_caf: Optional[float] = None               # Dette nette / CAF
    gearing: Optional[float] = None                    # Dette nette / Capitaux propres
    financial_autonomy: Optional[float] = None         # Capitaux propres / Total actif
    working_capital: Optional[float] = None            # Fonds de roulement (FR)
    wcr: Optional[float] = None                        # Besoin en fonds de roulement (BFR)
    net_cash_position: Optional[float] = None          # Trésorerie nette
    current_ratio: Optional[float] = None              # Liquidité générale
    quick_ratio: Optional[float] = None                # Liquidité immédiate
    interest_coverage: Optional[float] = None          # Couverture des intérêts (EBIT/Intérêts)
    debt_repayment_years: Optional[float] = None       # Années pour rembourser la dette


class SoliditeScore(BaseModel):
    score: float
    metrics: SoliditeMetrics
    risk_level: str                # "Faible" | "Modéré" | "Élevé" | "Très élevé"
    strengths: list[str]
    weaknesses: list[str]
    interpretation: str


# ---------------------------------------------------------------------------
# Flux de trésorerie (20%)
# ---------------------------------------------------------------------------

class FluxMetrics(BaseModel):
    operating_cash_flow: Optional[float] = None        # Flux opérationnels (dernière année)
    capex: Optional[float] = None                      # CAPEX
    free_cash_flow: Optional[float] = None             # FCF = OpCF - CAPEX
    fcf_per_share: Optional[float] = None              # FCF par action
    cash_conversion_ratio: Optional[float] = None      # FCF / Résultat net
    debt_coverage_by_fcf: Optional[float] = None       # FCF / Dette nette
    fcf_history: Optional[list[Optional[float]]] = None # FCF sur 5 ans
    operating_cf_history: Optional[list[Optional[float]]] = None  # Flux opérationnels sur 5 ans


class FluxScore(BaseModel):
    score: float
    metrics: FluxMetrics
    strengths: list[str]
    weaknesses: list[str]
    interpretation: str


# ---------------------------------------------------------------------------
# Valorisation (25%)
# ---------------------------------------------------------------------------

class ValuationZone:
    SOLDE = "Solde"
    ATTRACTIF = "Attractif"
    FAIR_VALUE = "Fair Value"
    CHER = "Cher"


class ValuationMethod(BaseModel):
    name: str
    target_solde: Optional[float] = None
    target_attractif: Optional[float] = None
    target_fair_value: Optional[float] = None
    target_cher: Optional[float] = None
    current_metric: Optional[float] = None     # valeur actuelle du ratio
    zone: Optional[str] = None                 # zone déterminée pour cette méthode


class ValuationZoneResult(BaseModel):
    zone: str                                  # zone consensus
    price_range_solde: Optional[tuple[Optional[float], Optional[float]]] = None
    price_range_attractif: Optional[tuple[Optional[float], Optional[float]]] = None
    price_range_fair_value: Optional[tuple[Optional[float], Optional[float]]] = None
    price_range_cher: Optional[tuple[Optional[float], Optional[float]]] = None
    current_price: Optional[float] = None
    fair_value_estimate: Optional[float] = None
    safety_margin_pct: Optional[float] = None  # % de marge par rapport à la fair value


class ValorisationMetrics(BaseModel):
    current_price: Optional[float] = None
    per_current: Optional[float] = None
    eps_ttm: Optional[float] = None            # BNA derniers 12 mois
    dividend_per_share: Optional[float] = None
    dividend_yield: Optional[float] = None     # %
    fcf_per_share: Optional[float] = None
    fcf_yield: Optional[float] = None          # %
    beta: Optional[float] = None
    market_cap: Optional[float] = None
    wacc: Optional[float] = None               # pour DCF
    dcf_value: Optional[float] = None


class ValorisationScore(BaseModel):
    score: float
    metrics: ValorisationMetrics
    methods: list[ValuationMethod]
    zone_result: ValuationZoneResult
    strengths: list[str]
    weaknesses: list[str]
    interpretation: str


# ---------------------------------------------------------------------------
# Score global
# ---------------------------------------------------------------------------

class GlobalScore(BaseModel):
    total: float                               # /100
    rentabilite: float                         # /100
    solidite: float                            # /100
    flux: float                                # /100
    valorisation: float                        # /100
    interpretation: str                        # "Excellence financière", etc.


# ---------------------------------------------------------------------------
# Réponse complète de l'analyse
# ---------------------------------------------------------------------------

class AnalysisResponse(BaseModel):
    ticker: str
    company_name: str
    currency: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    last_updated: str                          # ISO datetime

    global_score: GlobalScore
    rentabilite: RentabiliteScore
    solidite: SoliditeScore
    flux: FluxScore
    valorisation: ValorisationScore

    # Métriques clés pour le dashboard
    key_metrics: dict


# ---------------------------------------------------------------------------
# Réponse d'erreur
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    ticker: Optional[str] = None


# ---------------------------------------------------------------------------
# Événements SSE
# ---------------------------------------------------------------------------

class ProgressEvent(BaseModel):
    step: str          # "scraping" | "rentabilite" | "solidite" | "flux" | "valorisation" | "done"
    message: str
    progress: int      # 0-100
    data: Optional[dict] = None
