"""
Module d'intégration Financial Modeling Prep (FMP).

Utilisation en fallback/complément de yfinance pour l'historique long terme (10 ans)
des états financiers, métriques clés, bilan et flux de trésorerie.

Configuration:
    FMP_API_KEY : variable d'environnement requise
                  Obtenez une clé sur https://financialmodelingprep.com/

Exemple d'usage:
    from scraping.fmp_client import get_fmp_data, merge_yfinance_fmp
    from scraping.yfinance_scraper import scrape_ticker

    yf_data = scrape_ticker("MC.PA")
    fmp_data = get_fmp_data("MC.PA")
    merged   = merge_yfinance_fmp(yf_data, fmp_data)
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
_FMP_CACHE_DIR = Path(__file__).parent.parent / ".cache" / "fmp"
_CACHE_TTL_SECONDS = 86400  # 24h

_MEMORY_CACHE: dict[str, dict] = {}


def _get_api_key() -> str:
    key = os.environ.get("FMP_API_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "FMP_API_KEY non défini. "
            "Définissez la variable d'environnement avant d'appeler ce module."
        )
    return key


# ---------------------------------------------------------------------------
# Cache (même pattern que yfinance_scraper : mémoire + fichier JSON)
# ---------------------------------------------------------------------------

def _cache_path(cache_key: str) -> Path:
    _FMP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_key = cache_key.replace("/", "_").replace(".", "_")
    return _FMP_CACHE_DIR / f"{safe_key}.json"


def _load_cache(cache_key: str) -> Optional[Any]:
    if cache_key in _MEMORY_CACHE:
        entry = _MEMORY_CACHE[cache_key]
        if time.time() - entry["ts"] < _CACHE_TTL_SECONDS:
            return entry["data"]
        del _MEMORY_CACHE[cache_key]

    path = _cache_path(cache_key)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - raw["ts"] < _CACHE_TTL_SECONDS:
                _MEMORY_CACHE[cache_key] = raw
                return raw["data"]
        except Exception:
            pass
    return None


def _save_cache(cache_key: str, data: Any) -> None:
    entry = {"ts": time.time(), "data": data}
    _MEMORY_CACHE[cache_key] = entry
    try:
        _cache_path(cache_key).write_text(
            json.dumps(entry, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _fmp_get(path: str, params: Optional[dict] = None) -> Optional[Any]:
    """
    Appel GET vers l'API FMP avec gestion des erreurs réseau et rate-limit.

    Raises:
        EnvironmentError : clé API absente ou invalide
        RuntimeError     : rate limit (429) ou erreur réseau
    Returns:
        Données JSON parsées, ou None si le ticker/ressource est introuvable.
    """
    api_key = _get_api_key()
    full_params = {"apikey": api_key}
    if params:
        full_params.update(params)

    url = f"{_FMP_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=full_params)
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Timeout FMP ({url}) : {e}") from e
    except httpx.NetworkError as e:
        raise RuntimeError(f"Erreur réseau FMP ({url}) : {e}") from e

    if resp.status_code == 429:
        raise RuntimeError("FMP rate limit atteint (429). Réessayez plus tard.")
    if resp.status_code == 401:
        raise EnvironmentError("FMP_API_KEY invalide ou quota dépassé (401).")
    if resp.status_code != 200:
        return None

    data = resp.json()
    # FMP retourne {"Error Message": "..."} pour les tickers inconnus
    if isinstance(data, dict) and data.get("Error Message"):
        return None
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        return None if f != f else f  # NaN → None
    except (TypeError, ValueError):
        return None


def _cagr(values: list[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None and v > 0]
    if len(clean) < 2:
        return None
    n = len(clean) - 1
    try:
        return (clean[-1] / clean[0]) ** (1 / n) - 1
    except (ZeroDivisionError, ValueError):
        return None


def _extract_10y(
    records: list[dict], field: str
) -> tuple[list[Optional[float]], list[int]]:
    """
    Extrait jusqu'à 10 années d'une métrique depuis les records FMP.
    Les records doivent être triés en ordre ASC (du plus ancien au plus récent).
    """
    slice_ = records[-10:]
    values: list[Optional[float]] = []
    years: list[int] = []
    for rec in slice_:
        date_str = rec.get("date") or rec.get("calendarYear") or ""
        try:
            year = int(str(date_str)[:4])
        except (ValueError, TypeError):
            year = 0
        values.append(_safe_float(rec.get(field)))
        years.append(year)
    return values, years


# ---------------------------------------------------------------------------
# Endpoints FMP (chacun avec son propre cache)
# ---------------------------------------------------------------------------

def _fetch_income_statements(ticker: str, limit: int = 10) -> list[dict]:
    key = f"{ticker.upper()}__income"
    cached = _load_cache(key)
    if cached is not None:
        return cached
    data = _fmp_get(f"/income-statement/{ticker}", {"limit": limit, "period": "annual"})
    if not isinstance(data, list):
        return []
    records = list(reversed(data))  # FMP → DESC, on inverse en ASC
    _save_cache(key, records)
    return records


def _fetch_balance_sheets(ticker: str, limit: int = 10) -> list[dict]:
    key = f"{ticker.upper()}__balance"
    cached = _load_cache(key)
    if cached is not None:
        return cached
    data = _fmp_get(f"/balance-sheet-statement/{ticker}", {"limit": limit, "period": "annual"})
    if not isinstance(data, list):
        return []
    records = list(reversed(data))
    _save_cache(key, records)
    return records


def _fetch_cash_flows(ticker: str, limit: int = 10) -> list[dict]:
    key = f"{ticker.upper()}__cashflow"
    cached = _load_cache(key)
    if cached is not None:
        return cached
    data = _fmp_get(f"/cash-flow-statement/{ticker}", {"limit": limit, "period": "annual"})
    if not isinstance(data, list):
        return []
    records = list(reversed(data))
    _save_cache(key, records)
    return records


def _fetch_key_metrics(ticker: str, limit: int = 10) -> list[dict]:
    key = f"{ticker.upper()}__metrics"
    cached = _load_cache(key)
    if cached is not None:
        return cached
    data = _fmp_get(f"/key-metrics/{ticker}", {"limit": limit, "period": "annual"})
    if not isinstance(data, list):
        return []
    records = list(reversed(data))
    _save_cache(key, records)
    return records


def _fetch_profile(ticker: str) -> dict:
    key = f"{ticker.upper()}__profile"
    cached = _load_cache(key)
    if cached is not None:
        return cached
    data = _fmp_get(f"/profile/{ticker}")
    if not isinstance(data, list) or not data:
        return {}
    profile = data[0]
    _save_cache(key, profile)
    return profile


# ---------------------------------------------------------------------------
# Interface principale
# ---------------------------------------------------------------------------

def get_fmp_data(ticker: str) -> dict:
    """
    Récupère les données financières complètes depuis FMP pour un ticker.

    Supporte les tickers européens (ex: "MC.PA", "AIR.PA", "ASML.AS").
    Pour les tickers .PA, FMP utilise la notation avec extension (identique à yfinance).

    Args:
        ticker : Symbole boursier (ex: "AAPL", "MC.PA", "ASML.AS")

    Returns:
        Dict normalisé avec la même structure que scrape_ticker() de yfinance_scraper.
        Contient un champ "source": "fmp" pour traçabilité.

    Raises:
        EnvironmentError : FMP_API_KEY absent ou invalide
        ValueError       : ticker introuvable sur FMP
        RuntimeError     : rate limit ou erreur réseau
    """
    t = ticker.upper()

    full_key = f"{t}__full"
    cached = _load_cache(full_key)
    if cached is not None:
        return cached

    income = _fetch_income_statements(t)
    balance = _fetch_balance_sheets(t)
    cashflow = _fetch_cash_flows(t)
    metrics = _fetch_key_metrics(t)
    profile = _fetch_profile(t)

    if not income and not profile:
        raise ValueError(f"Ticker '{ticker}' introuvable sur FMP.")

    last_income = income[-1] if income else {}
    last_balance = balance[-1] if balance else {}
    last_cashflow = cashflow[-1] if cashflow else {}
    last_metrics = metrics[-1] if metrics else {}

    # -------------------------------------------------------------------------
    # Compte de résultat (10 ans)
    # -------------------------------------------------------------------------
    revenues, years = _extract_10y(income, "revenue")
    gross_profits, _ = _extract_10y(income, "grossProfit")
    operating_incomes, _ = _extract_10y(income, "operatingIncome")
    net_incomes, _ = _extract_10y(income, "netIncome")
    ebitdas, _ = _extract_10y(income, "ebitda")
    eps_history, _ = _extract_10y(income, "eps")
    interest_expenses, _ = _extract_10y(income, "interestExpense")

    latest_revenue = _safe_float(last_income.get("revenue"))
    latest_gross = _safe_float(last_income.get("grossProfit"))
    latest_op = _safe_float(last_income.get("operatingIncome"))
    latest_net = _safe_float(last_income.get("netIncome"))
    latest_ebitda = _safe_float(last_income.get("ebitda"))

    gross_margin = (latest_gross / latest_revenue) if latest_gross and latest_revenue else None
    operating_margin = (latest_op / latest_revenue) if latest_op and latest_revenue else None
    net_margin = (latest_net / latest_revenue) if latest_net and latest_revenue else None

    # -------------------------------------------------------------------------
    # Bilan
    # -------------------------------------------------------------------------
    total_assets = _safe_float(last_balance.get("totalAssets"))
    total_equity = _safe_float(last_balance.get("totalStockholdersEquity"))
    total_debt = _safe_float(last_balance.get("totalDebt"))
    cash = _safe_float(
        last_balance.get("cashAndCashEquivalents")
        or last_balance.get("cashAndShortTermInvestments")
    )
    current_assets = _safe_float(last_balance.get("totalCurrentAssets"))
    current_liabilities = _safe_float(last_balance.get("totalCurrentLiabilities"))
    inventory = _safe_float(last_balance.get("inventory"))
    long_term_debt = _safe_float(last_balance.get("longTermDebt"))

    net_debt = (total_debt - cash) if total_debt is not None and cash is not None else None

    # -------------------------------------------------------------------------
    # Flux de trésorerie (10 ans)
    # -------------------------------------------------------------------------
    op_cf_list, _ = _extract_10y(cashflow, "operatingCashFlow")
    capex_raw, _ = _extract_10y(cashflow, "capitalExpenditure")
    # CAPEX est négatif dans FMP (décaissement) → valeur absolue
    capex_list = [abs(v) if v is not None else None for v in capex_raw]
    fcf_list, _ = _extract_10y(cashflow, "freeCashFlow")
    dividends_paid_list, _ = _extract_10y(cashflow, "dividendsPaid")

    latest_op_cf = op_cf_list[-1] if op_cf_list else None
    latest_capex = capex_list[-1] if capex_list else None
    latest_fcf = fcf_list[-1] if fcf_list else None

    if latest_fcf is None and latest_op_cf is not None and latest_capex is not None:
        latest_fcf = latest_op_cf - latest_capex

    # Historique FCF cohérent même si FMP ne l'expose pas directement
    if not any(v is not None for v in fcf_list):
        fcf_list = [
            (op - cap) if op is not None and cap is not None else None
            for op, cap in zip(op_cf_list, capex_list)
        ]

    # -------------------------------------------------------------------------
    # Key metrics (historique ratios)
    # -------------------------------------------------------------------------
    per_history, _ = _extract_10y(metrics, "peRatio")
    ev_ebitda_history, _ = _extract_10y(metrics, "enterpriseValueOverEBITDA")
    roe_history, _ = _extract_10y(metrics, "roe")
    roce_history, _ = _extract_10y(metrics, "returnOnCapitalEmployed")

    per = _safe_float(last_metrics.get("peRatio")) or _safe_float(profile.get("pe"))
    roe = _safe_float(last_metrics.get("roe"))
    roa = _safe_float(last_metrics.get("returnOnAssets"))
    roce = _safe_float(last_metrics.get("returnOnCapitalEmployed"))
    ev_ebitda = _safe_float(last_metrics.get("enterpriseValueOverEBITDA"))
    dividend_yield = _safe_float(last_metrics.get("dividendYield"))

    # -------------------------------------------------------------------------
    # Profil entreprise
    # -------------------------------------------------------------------------
    company_name = profile.get("companyName") or ticker
    currency = profile.get("currency", "USD")
    sector = profile.get("sector")
    industry = profile.get("industry")
    market_cap = _safe_float(profile.get("mktCap"))
    current_price = _safe_float(profile.get("price"))
    beta = _safe_float(profile.get("beta"))
    shares_outstanding = _safe_float(profile.get("sharesOutstanding"))

    # -------------------------------------------------------------------------
    # Ratios calculés
    # -------------------------------------------------------------------------
    ebitda = latest_ebitda

    net_debt_ebitda = None
    if net_debt is not None and ebitda and ebitda > 0:
        net_debt_ebitda = net_debt / ebitda

    caf = latest_op_cf
    net_debt_caf = None
    if net_debt is not None and caf and caf > 0:
        net_debt_caf = net_debt / caf

    gearing = None
    if net_debt is not None and total_equity and total_equity > 0:
        gearing = net_debt / total_equity

    financial_autonomy = None
    if total_equity is not None and total_assets:
        financial_autonomy = total_equity / total_assets

    current_ratio = None
    if current_assets is not None and current_liabilities and current_liabilities > 0:
        current_ratio = current_assets / current_liabilities

    quick_ratio = None
    if current_assets is not None and current_liabilities and current_liabilities > 0:
        inv = inventory or 0
        quick_ratio = (current_assets - inv) / current_liabilities

    fcf_per_share = None
    if latest_fcf is not None and shares_outstanding:
        fcf_per_share = latest_fcf / shares_outstanding

    fcf_yield = None
    if fcf_per_share is not None and current_price:
        fcf_yield = fcf_per_share / current_price

    latest_interest = interest_expenses[-1] if interest_expenses else None
    interest_coverage = None
    if latest_op is not None and latest_interest is not None and latest_interest != 0:
        interest_coverage = abs(latest_op) / abs(latest_interest)

    wcr = None
    if current_assets is not None and current_liabilities is not None:
        inv = inventory or 0
        wcr = (current_assets - inv) - current_liabilities

    eps_ttm = eps_history[-1] if eps_history else None

    cash_conversion = None
    if latest_fcf is not None and latest_net and latest_net != 0:
        cash_conversion = latest_fcf / latest_net

    debt_coverage_fcf = None
    if latest_fcf is not None and net_debt and net_debt > 0:
        debt_coverage_fcf = latest_fcf / net_debt

    debt_repayment_years = None
    if net_debt is not None and caf and caf > 0 and net_debt > 0:
        debt_repayment_years = net_debt / caf

    revenue_cagr = _cagr(revenues)
    eps_cagr = _cagr(eps_history)

    # Dividendes payés (négatifs dans FMP → valeur absolue)
    dividend_history = [abs(v) if v is not None else None for v in dividends_paid_list]
    dividend_cagr = _cagr(dividend_history)

    # -------------------------------------------------------------------------
    # Dict normalisé (même structure que scrape_ticker de yfinance_scraper)
    # -------------------------------------------------------------------------
    data: dict = {
        # Traçabilité source
        "source": "fmp",

        # Identification
        "ticker": t,
        "company_name": company_name,
        "currency": currency,
        "sector": sector,
        "industry": industry,
        "last_updated": datetime.now(timezone.utc).isoformat(),

        # Prix & marché
        "current_price": current_price,
        "market_cap": market_cap,
        "shares_outstanding": shares_outstanding,
        "beta": beta,
        "per": per,

        # Compte de résultat (10 ans)
        "revenues": revenues,
        "gross_profits": gross_profits,
        "operating_incomes": operating_incomes,
        "net_incomes": net_incomes,
        "ebitdas": ebitdas,
        "interest_expenses": interest_expenses,
        "years": years,
        "ebitda": ebitda,
        "latest_revenue": latest_revenue,
        "latest_net_income": latest_net,
        "latest_ebitda": ebitda,

        # Marges
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,

        # CAGR
        "revenue_cagr_10y": revenue_cagr,
        "eps_cagr_10y": eps_cagr,
        "dividend_cagr_10y": dividend_cagr,

        # Par action
        "eps_ttm": eps_ttm,
        "eps_history": eps_history,
        "dividend_per_share": None,  # non disponible directement dans FMP income stmt
        "dividend_yield": dividend_yield,
        "dividend_history": dividend_history,
        "div_history_years": years[-len(dividend_history) :] if dividend_history else [],
        "fcf_per_share": fcf_per_share,
        "fcf_yield": fcf_yield,

        # Rentabilité
        "roe": roe,
        "roa": roa,
        "roce": roce,

        # Historiques ratios (spécifiques FMP, non présents dans yfinance_scraper)
        "per_history": per_history,
        "ev_ebitda_history": ev_ebitda_history,
        "roe_history": roe_history,
        "roce_history": roce_history,
        "ev_ebitda": ev_ebitda,

        # Bilan
        "total_assets": total_assets,
        "total_equity": total_equity,
        "total_debt": total_debt,
        "long_term_debt": long_term_debt,
        "cash": cash,
        "net_debt": net_debt,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "inventory": inventory,

        # Ratios solidité
        "net_debt_ebitda": net_debt_ebitda,
        "net_debt_caf": net_debt_caf,
        "gearing": gearing,
        "financial_autonomy": financial_autonomy,
        "working_capital": (
            (current_assets - current_liabilities)
            if current_assets is not None and current_liabilities is not None
            else None
        ),
        "wcr": wcr,
        "net_cash_position": (cash - (current_liabilities or 0)) if cash else None,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "interest_coverage": interest_coverage,
        "debt_repayment_years": debt_repayment_years,

        # Flux (10 ans)
        "operating_cf": latest_op_cf,
        "capex": latest_capex,
        "fcf": latest_fcf,
        "fcf_history": fcf_list,
        "operating_cf_history": op_cf_list,
        "capex_history": capex_list,
        "cash_conversion": cash_conversion,
        "debt_coverage_fcf": debt_coverage_fcf,
        "caf": caf,
    }

    _save_cache(full_key, data)
    return data


def merge_yfinance_fmp(yf_data: dict, fmp_data: dict) -> dict:
    """
    Fusionne les données yfinance (source primaire) avec FMP (source secondaire).

    Stratégie :
    - Les données temps-réel de yfinance (prix, PE, market cap) ont la priorité.
    - FMP complète les champs manquants (None) de yfinance.
    - Pour les séries historiques, FMP est préféré s'il fournit plus d'années.
    - Les champs exclusifs FMP (per_history, ev_ebitda, roce…) sont ajoutés systématiquement.

    Args:
        yf_data  : dict retourné par scrape_ticker()
        fmp_data : dict retourné par get_fmp_data()

    Returns:
        Dict fusionné avec "source": "merged_yf_fmp"
    """
    merged = dict(yf_data)
    merged["source"] = "merged_yf_fmp"

    # Séries historiques : préférer FMP si plus longue ou si yfinance est vide
    historical_fields = [
        "revenues",
        "gross_profits",
        "operating_incomes",
        "net_incomes",
        "ebitdas",
        "interest_expenses",
        "years",
        "eps_history",
        "fcf_history",
        "operating_cf_history",
        "capex_history",
    ]
    for field in historical_fields:
        yf_val = yf_data.get(field) or []
        fmp_val = fmp_data.get(field) or []
        if len(fmp_val) > len(yf_val):
            merged[field] = fmp_val

    # Champs scalaires : combler les None de yfinance avec FMP
    scalar_fields = [
        "ebitda",
        "latest_ebitda",
        "revenue_cagr_10y",
        "eps_cagr_10y",
        "dividend_cagr_10y",
        "dividend_history",
        "div_history_years",
        "roe",
        "roa",
    ]
    for field in scalar_fields:
        if merged.get(field) is None and fmp_data.get(field) is not None:
            merged[field] = fmp_data[field]

    # Champs exclusifs FMP (non produits par yfinance_scraper) : toujours ajouter
    fmp_exclusive = [
        "roce",
        "ev_ebitda",
        "per_history",
        "ev_ebitda_history",
        "roe_history",
        "roce_history",
    ]
    for field in fmp_exclusive:
        if fmp_data.get(field) is not None:
            merged[field] = fmp_data[field]

    return merged
