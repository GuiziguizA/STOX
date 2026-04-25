"""
Module de scraping des données financières via yfinance.
Cache 24h pour éviter les re-scraping excessifs.
"""
import json
import time
from datetime import datetime, timedelta
from itertools import zip_longest
from pathlib import Path
from typing import Any, Optional

import yfinance as yf

# ---------------------------------------------------------------------------
# Cache en mémoire + fichier JSON (TTL 24h)
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(__file__).parent.parent / ".cache"
_CACHE_TTL_SECONDS = 86400  # 24h

_MEMORY_CACHE: dict[str, dict] = {}


def _cache_path(ticker: str) -> Path:
    _CACHE_DIR.mkdir(exist_ok=True)
    return _CACHE_DIR / f"{ticker.upper()}.json"


def _load_cache(ticker: str) -> Optional[dict]:
    key = ticker.upper()

    # 1) Mémoire d'abord
    if key in _MEMORY_CACHE:
        entry = _MEMORY_CACHE[key]
        if time.time() - entry["ts"] < _CACHE_TTL_SECONDS:
            return entry["data"]
        del _MEMORY_CACHE[key]

    # 2) Fichier disque
    path = _cache_path(ticker)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - raw["ts"] < _CACHE_TTL_SECONDS:
                _MEMORY_CACHE[key] = raw
                return raw["data"]
        except Exception:
            pass
    return None


def _save_cache(ticker: str, data: dict) -> None:
    key = ticker.upper()
    entry = {"ts": time.time(), "data": data}
    _MEMORY_CACHE[key] = entry
    try:
        _cache_path(ticker).write_text(
            json.dumps(entry, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
    """Convertit proprement en float, None si impossible."""
    try:
        if value is None:
            return None
        f = float(value)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _series_to_list(series, n: int = 10) -> list[Optional[float]]:
    """Convertit une pd.Series en liste de float (les n dernières valeurs)."""
    if series is None or len(series) == 0:
        return []
    values = [_safe_float(v) for v in series.values[-n:]]
    return values


def _series_years(series, n: int = 10) -> list[int]:
    """Extrait les années d'une pd.Series datée."""
    if series is None or len(series) == 0:
        return []
    return [int(idx.year) for idx in series.index[-n:]]


def _cagr(values: list[Optional[float]]) -> Optional[float]:
    """
    Calcule le CAGR (Taux de croissance annuel composé) sur une liste de valeurs.
    Retourne None si insuffisant.
    """
    clean = [v for v in values if v is not None and v > 0]
    if len(clean) < 2:
        return None
    n = len(clean) - 1
    try:
        return (clean[-1] / clean[0]) ** (1 / n) - 1
    except (ZeroDivisionError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Scraping principal
# ---------------------------------------------------------------------------

def scrape_ticker(ticker: str) -> dict:
    """
    Récupère et structure toutes les données financières d'un ticker.
    Retourne un dict normalisé utilisé par les modules d'analyse.
    Lance une ValueError si le ticker est invalide.
    """
    cached = _load_cache(ticker)
    if cached is not None:
        return cached

    t = yf.Ticker(ticker)

    # Validation du ticker
    try:
        info = t.info
        if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
            # Tentative de récupération du prix via fast_info
            fast = t.fast_info
            if not hasattr(fast, "last_price") or fast.last_price is None:
                raise ValueError(f"Ticker « {ticker} » introuvable ou sans données de marché.")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Erreur lors de la récupération de « {ticker} » : {e}") from e

    # Prix courant
    current_price = _safe_float(
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )

    # Données annuelles
    financials = t.financials          # compte de résultat (colonnes = dates)
    balance_sheet = t.balance_sheet    # bilan
    cashflow = t.cashflow              # flux de trésorerie
    income_stmt_q = t.quarterly_financials  # trimestriel pour TTM

    # Historique annuel (yfinance retourne en ordre décroissant — on inverse)
    fin = financials.sort_index(axis=1) if financials is not None and not financials.empty else None
    bs = balance_sheet.sort_index(axis=1) if balance_sheet is not None and not balance_sheet.empty else None
    cf = cashflow.sort_index(axis=1) if cashflow is not None and not cashflow.empty else None

    def get_row(df, *keys) -> Optional[Any]:
        if df is None:
            return None
        for key in keys:
            if key in df.index:
                return df.loc[key]
        return None

    # -------------------------------------------------------------------------
    # Compte de résultat
    # -------------------------------------------------------------------------
    revenue_series = get_row(fin, "Total Revenue", "Revenue")
    gross_profit_series = get_row(fin, "Gross Profit")
    operating_income_series = get_row(fin, "Operating Income", "Ebit")
    net_income_series = get_row(fin, "Net Income")
    ebitda_series = get_row(fin, "EBITDA", "Normalized EBITDA")
    interest_expense_series = get_row(fin, "Interest Expense", "Interest Expense Non Operating")

    revenues = _series_to_list(revenue_series, 10)
    gross_profits = _series_to_list(gross_profit_series, 10)
    operating_incomes = _series_to_list(operating_income_series, 10)
    net_incomes = _series_to_list(net_income_series, 10)
    ebitdas = _series_to_list(ebitda_series, 10)
    interest_expenses = _series_to_list(interest_expense_series, 10)
    years = _series_years(revenue_series, 10) if revenue_series is not None else []

    # Marges (dernière année disponible)
    latest_revenue = revenues[-1] if revenues else None
    latest_gross = gross_profits[-1] if gross_profits else None
    latest_op = operating_incomes[-1] if operating_incomes else None
    latest_net = net_incomes[-1] if net_incomes else None
    latest_ebitda = ebitdas[-1] if ebitdas else None
    latest_interest = interest_expenses[-1] if interest_expenses else None

    gross_margin = (latest_gross / latest_revenue) if latest_gross and latest_revenue else None
    operating_margin = (latest_op / latest_revenue) if latest_op and latest_revenue else None
    net_margin = (latest_net / latest_revenue) if latest_net and latest_revenue else None

    # -------------------------------------------------------------------------
    # Bilan
    # -------------------------------------------------------------------------
    total_assets_s = get_row(bs, "Total Assets")
    total_equity_s = get_row(bs, "Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity")
    total_debt_s = get_row(bs, "Total Debt", "Long Term Debt And Capital Lease Obligation")
    short_term_debt_s = get_row(bs, "Current Debt", "Short Long Term Debt", "Short Term Debt")
    cash_s = get_row(bs, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
    current_assets_s = get_row(bs, "Current Assets", "Total Current Assets")
    current_liabilities_s = get_row(bs, "Current Liabilities", "Total Current Liabilities")
    inventory_s = get_row(bs, "Inventory")
    long_term_debt_s = get_row(bs, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")

    total_assets = _safe_float(total_assets_s.iloc[-1] if total_assets_s is not None and len(total_assets_s) > 0 else None)
    total_equity = _safe_float(total_equity_s.iloc[-1] if total_equity_s is not None and len(total_equity_s) > 0 else None)
    total_debt = _safe_float(total_debt_s.iloc[-1] if total_debt_s is not None and len(total_debt_s) > 0 else None)
    cash = _safe_float(cash_s.iloc[-1] if cash_s is not None and len(cash_s) > 0 else None)
    current_assets = _safe_float(current_assets_s.iloc[-1] if current_assets_s is not None and len(current_assets_s) > 0 else None)
    current_liabilities = _safe_float(current_liabilities_s.iloc[-1] if current_liabilities_s is not None and len(current_liabilities_s) > 0 else None)
    inventory = _safe_float(inventory_s.iloc[-1] if inventory_s is not None and len(inventory_s) > 0 else None)
    long_term_debt = _safe_float(long_term_debt_s.iloc[-1] if long_term_debt_s is not None and len(long_term_debt_s) > 0 else None)

    net_debt = None
    if total_debt is not None and cash is not None:
        net_debt = total_debt - cash

    # -------------------------------------------------------------------------
    # Flux de trésorerie
    # -------------------------------------------------------------------------
    operating_cf_series = get_row(cf, "Operating Cash Flow", "Total Cash From Operating Activities")
    capex_series = get_row(cf, "Capital Expenditure", "Capital Expenditures")

    operating_cf_list = _series_to_list(operating_cf_series, 5)
    capex_list = _series_to_list(capex_series, 5)

    latest_op_cf = operating_cf_list[-1] if operating_cf_list else None
    latest_capex = capex_list[-1] if capex_list else None

    # CAPEX souvent négatif dans yfinance → valeur absolue
    if latest_capex is not None and latest_capex < 0:
        latest_capex = abs(latest_capex)
        capex_list = [abs(v) if v is not None else None for v in capex_list]

    fcf = None
    if latest_op_cf is not None and latest_capex is not None:
        fcf = latest_op_cf - latest_capex

    fcf_history = []
    for op, cap in zip_longest(operating_cf_list, capex_list):
        if op is not None and cap is not None:
            fcf_history.append(op - cap)
        else:
            fcf_history.append(None)

    # -------------------------------------------------------------------------
    # Données par action & marché
    # -------------------------------------------------------------------------
    shares_outstanding = _safe_float(info.get("sharesOutstanding"))
    eps_ttm = _safe_float(info.get("trailingEps"))
    dividend_per_share = _safe_float(info.get("dividendRate") or info.get("trailingAnnualDividendRate"))
    dividend_yield = _safe_float(info.get("dividendYield") or info.get("trailingAnnualDividendYield"))
    beta = _safe_float(info.get("beta"))
    market_cap = _safe_float(info.get("marketCap"))
    per = _safe_float(info.get("trailingPE") or info.get("forwardPE"))

    # ROE, ROA depuis info yfinance ou calcul manuel
    roe = _safe_float(info.get("returnOnEquity"))
    roa = _safe_float(info.get("returnOnAssets"))
    if roe is None and latest_net and total_equity:
        roe = latest_net / total_equity if total_equity != 0 else None
    if roa is None and latest_net and total_assets:
        roa = latest_net / total_assets if total_assets != 0 else None

    # FCF par action
    fcf_per_share = None
    if fcf is not None and shares_outstanding:
        fcf_per_share = fcf / shares_outstanding

    # FCF yield
    fcf_yield = None
    if fcf_per_share is not None and current_price:
        fcf_yield = fcf_per_share / current_price

    # Couverture des intérêts
    interest_coverage = None
    if latest_op is not None and latest_interest is not None and latest_interest != 0:
        interest_coverage = abs(latest_op) / abs(latest_interest)

    # BFR
    wcr = None
    if current_assets is not None and current_liabilities is not None:
        inv = inventory or 0
        wcr = (current_assets - inv) - current_liabilities  # simplifié

    # Historique EPS (via income stmt)
    eps_series = get_row(fin, "Diluted EPS", "Basic EPS", "Diluted Average Shares")
    if eps_series is not None:
        eps_history = _series_to_list(eps_series, 10)
    elif net_incomes and shares_outstanding:
        eps_history = [v / shares_outstanding if v is not None else None for v in net_incomes]
    else:
        eps_history = []

    # Historique dividendes
    try:
        dividends = t.dividends
        if dividends is not None and not dividends.empty:
            # Agréger par année
            div_by_year = dividends.groupby(dividends.index.year).sum()
            div_years = list(div_by_year.index[-10:])
            div_values = [_safe_float(v) for v in div_by_year.values[-10:]]
            dividend_history = div_values
            div_history_years = div_years
        else:
            dividend_history = []
            div_history_years = []
    except Exception:
        dividend_history = []
        div_history_years = []

    # CAGR calculs
    revenue_cagr = _cagr(revenues)
    eps_cagr = _cagr(eps_history)
    dividend_cagr = _cagr(dividend_history)

    # EBITDA et ratios de dette
    ebitda = latest_ebitda
    if ebitda is None and latest_op is not None:
        # Approximation EBITDA ≈ EBIT + D&A
        da_series = get_row(cf, "Depreciation And Amortization", "Depreciation")
        da = _safe_float(da_series.iloc[-1] if da_series is not None and len(da_series) > 0 else None)
        if da is not None:
            ebitda = latest_op + abs(da)

    net_debt_ebitda = None
    if net_debt is not None and ebitda and ebitda > 0:
        net_debt_ebitda = net_debt / ebitda

    caf = latest_op_cf  # CAF ≈ Flux opérationnels dans notre contexte
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

    debt_repayment_years = None
    if net_debt is not None and caf and caf > 0 and net_debt > 0:
        debt_repayment_years = net_debt / caf

    # Cash conversion
    cash_conversion = None
    if fcf is not None and latest_net and latest_net != 0:
        cash_conversion = fcf / latest_net

    debt_coverage_fcf = None
    if fcf is not None and net_debt and net_debt > 0:
        debt_coverage_fcf = fcf / net_debt

    # -------------------------------------------------------------------------
    # Rassembler toutes les données
    # -------------------------------------------------------------------------
    data = {
        # Identification
        "ticker": ticker.upper(),
        "company_name": info.get("longName") or info.get("shortName") or ticker.upper(),
        "currency": info.get("currency", "USD"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "last_updated": datetime.utcnow().isoformat(),

        # Prix & marché
        "current_price": current_price,
        "market_cap": market_cap,
        "shares_outstanding": shares_outstanding,
        "beta": beta,
        "per": per,

        # Compte de résultat
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
        "dividend_per_share": dividend_per_share,
        "dividend_yield": dividend_yield,
        "dividend_history": dividend_history,
        "div_history_years": div_history_years,
        "fcf_per_share": fcf_per_share,
        "fcf_yield": fcf_yield,

        # Rentabilité
        "roe": roe,
        "roa": roa,

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
        "working_capital": (current_assets - current_liabilities) if current_assets and current_liabilities else None,
        "wcr": wcr,
        "net_cash_position": (cash - (current_liabilities or 0)) if cash else None,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "interest_coverage": interest_coverage,
        "debt_repayment_years": debt_repayment_years,

        # Flux
        "operating_cf": latest_op_cf,
        "capex": latest_capex,
        "fcf": fcf,
        "fcf_history": fcf_history,
        "operating_cf_history": operating_cf_list,
        "capex_history": capex_list,
        "cash_conversion": cash_conversion,
        "debt_coverage_fcf": debt_coverage_fcf,
        "caf": caf,
    }

    _save_cache(ticker, data)
    return data
