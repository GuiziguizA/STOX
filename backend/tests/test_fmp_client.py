"""
Tests unitaires pour scraping/fmp_client.py.
Tous les appels HTTP vers FMP sont mockés — aucun accès réseau réel.

Lancement :
    cd backend
    pytest tests/test_fmp_client.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Assure que le répertoire backend/ est dans le path lorsqu'on lance depuis backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraping.fmp_client import (
    _cagr,
    _extract_10y,
    _safe_float,
    get_fmp_data,
    merge_yfinance_fmp,
)

# ---------------------------------------------------------------------------
# Fixtures — données FMP simulées
# ---------------------------------------------------------------------------

INCOME_RECORDS = [
    {
        "date": "2015-12-31",
        "revenue": 50_000_000_000,
        "grossProfit": 30_000_000_000,
        "operatingIncome": 15_000_000_000,
        "netIncome": 10_000_000_000,
        "ebitda": 18_000_000_000,
        "eps": 5.0,
        "interestExpense": -500_000_000,
    },
    {
        "date": "2016-12-31",
        "revenue": 55_000_000_000,
        "grossProfit": 33_000_000_000,
        "operatingIncome": 17_000_000_000,
        "netIncome": 12_000_000_000,
        "ebitda": 20_000_000_000,
        "eps": 6.0,
        "interestExpense": -600_000_000,
    },
    {
        "date": "2024-12-31",
        "revenue": 100_000_000_000,
        "grossProfit": 60_000_000_000,
        "operatingIncome": 30_000_000_000,
        "netIncome": 20_000_000_000,
        "ebitda": 35_000_000_000,
        "eps": 10.0,
        "interestExpense": -1_000_000_000,
    },
]

BALANCE_RECORDS = [
    {
        "date": "2024-12-31",
        "totalAssets": 200_000_000_000,
        "totalStockholdersEquity": 80_000_000_000,
        "totalDebt": 50_000_000_000,
        "cashAndCashEquivalents": 20_000_000_000,
        "totalCurrentAssets": 60_000_000_000,
        "totalCurrentLiabilities": 30_000_000_000,
        "inventory": 5_000_000_000,
        "longTermDebt": 40_000_000_000,
    }
]

CASHFLOW_RECORDS = [
    {
        "date": "2024-12-31",
        "operatingCashFlow": 25_000_000_000,
        "capitalExpenditure": -5_000_000_000,
        "freeCashFlow": 20_000_000_000,
        "dividendsPaid": -3_000_000_000,
    }
]

METRICS_RECORDS = [
    {
        "date": "2024-12-31",
        "peRatio": 22.5,
        "enterpriseValueOverEBITDA": 18.0,
        "roe": 0.25,
        "returnOnCapitalEmployed": 0.20,
        "returnOnAssets": 0.10,
        "dividendYield": 0.02,
    }
]

PROFILE = {
    "companyName": "TestCorp",
    "currency": "EUR",
    "sector": "Technology",
    "industry": "Software",
    "mktCap": 500_000_000_000,
    "price": 250.0,
    "beta": 1.1,
    "sharesOutstanding": 2_000_000_000,
}


def _make_mock_response(json_data, status_code: int = 200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    return mock


# ---------------------------------------------------------------------------
# Tests : helpers
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_valid_int(self):
        assert _safe_float(42) == 42.0

    def test_valid_string(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None

    def test_zero(self):
        assert _safe_float(0) == 0.0


class TestCagr:
    def test_basic(self):
        result = _cagr([100.0, 200.0])
        assert result == pytest.approx(1.0)  # 100% sur 1 an

    def test_5y(self):
        # 100 → 161 en 5 ans ≈ 10% CAGR
        result = _cagr([100.0, 110.0, 121.0, 133.1, 146.41, 161.05])
        assert result == pytest.approx(0.10, abs=0.001)

    def test_insufficient_data(self):
        assert _cagr([]) is None
        assert _cagr([100.0]) is None

    def test_with_none(self):
        # [100, None, 121] → clean=[100, 121], n=1 → CAGR = 21%
        result = _cagr([100.0, None, 121.0])
        assert result == pytest.approx(0.21, abs=0.001)

    def test_negative_values_ignored(self):
        assert _cagr([-100.0, -50.0]) is None


class TestExtract10y:
    def test_basic(self):
        records = [
            {"date": "2020-12-31", "revenue": 100},
            {"date": "2021-12-31", "revenue": 200},
        ]
        values, years = _extract_10y(records, "revenue")
        assert values == [100.0, 200.0]
        assert years == [2020, 2021]

    def test_missing_field(self):
        records = [{"date": "2020-12-31"}]
        values, years = _extract_10y(records, "revenue")
        assert values == [None]
        assert years == [2020]

    def test_truncates_to_10(self):
        records = [{"date": f"200{i}-12-31", "val": i} for i in range(15)]
        values, years = _extract_10y(records, "val")
        assert len(values) == 10
        assert len(years) == 10

    def test_empty(self):
        values, years = _extract_10y([], "revenue")
        assert values == []
        assert years == []


# ---------------------------------------------------------------------------
# Tests : get_fmp_data avec HTTP mocké
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_memory_cache():
    """Vide le cache mémoire et disque des tickers de test avant chaque test."""
    from scraping import fmp_client
    fmp_client._MEMORY_CACHE.clear()

    # Supprime les fichiers disque des tickers utilisés dans les tests
    _test_tickers = ["TEST", "CACHED", "MC.PA", "INVALID_TICKER_XYZ"]
    _endpoints = ["full", "income", "balance", "cashflow", "metrics", "profile"]
    for _t in _test_tickers:
        for _ep in _endpoints:
            _p = fmp_client._cache_path(f"{_t.upper()}__{_ep}")
            if _p.exists():
                _p.unlink(missing_ok=True)

    yield

    fmp_client._MEMORY_CACHE.clear()


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test_key_123")


def _patch_fmp_endpoints(income=None, balance=None, cashflow=None, metrics=None, profile=None):
    """Helper pour patcher les 5 endpoints FMP d'un coup."""
    return patch(
        "scraping.fmp_client._fmp_get",
        side_effect=_make_fmp_get_side_effect(
            income=income or list(reversed(INCOME_RECORDS)),
            balance=balance or list(reversed(BALANCE_RECORDS)),
            cashflow=cashflow or list(reversed(CASHFLOW_RECORDS)),
            metrics=metrics or list(reversed(METRICS_RECORDS)),
            profile=[PROFILE],
        ),
    )


def _make_fmp_get_side_effect(income, balance, cashflow, metrics, profile):
    """Retourne la bonne réponse selon le path appelé."""
    def side_effect(path, params=None):
        if "/income-statement/" in path:
            return income
        if "/balance-sheet-statement/" in path:
            return balance
        if "/cash-flow-statement/" in path:
            return cashflow
        if "/key-metrics/" in path:
            return metrics
        if "/profile/" in path:
            return profile
        return None
    return side_effect


class TestGetFmpData:
    def test_returns_dict_with_required_keys(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")

        assert isinstance(data, dict)
        required_keys = [
            "ticker", "company_name", "currency", "revenues", "years",
            "net_incomes", "ebitdas", "fcf", "net_debt", "roe", "per",
        ]
        for key in required_keys:
            assert key in data, f"Clé manquante : {key}"

    def test_ticker_normalized_uppercase(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("test")
        assert data["ticker"] == "TEST"

    def test_source_is_fmp(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")
        assert data["source"] == "fmp"

    def test_revenues_sorted_asc(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")
        # INCOME_RECORDS inversés → après inversion dans _fetch, ASC
        assert data["revenues"][0] < data["revenues"][-1]

    def test_capex_positive(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")
        # CAPEX négatif en entrée → doit être positif en sortie
        assert data["capex"] is None or data["capex"] >= 0
        for v in data["capex_history"]:
            assert v is None or v >= 0

    def test_net_debt_computed(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")
        expected = 50_000_000_000 - 20_000_000_000
        assert data["net_debt"] == pytest.approx(expected)

    def test_margins_computed(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")
        # operating_margin = operatingIncome / revenue = 30B / 100B = 0.30
        assert data["operating_margin"] == pytest.approx(0.30)
        assert data["net_margin"] == pytest.approx(0.20)

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="FMP_API_KEY"):
            get_fmp_data("TEST")

    def test_unknown_ticker_raises_value_error(self):
        with patch("scraping.fmp_client._fmp_get", return_value=None):
            with pytest.raises(ValueError, match="introuvable"):
                get_fmp_data("INVALID_TICKER_XYZ")

    def test_rate_limit_propagated(self, monkeypatch):
        def raise_rate_limit(path, params=None):
            raise RuntimeError("FMP rate limit atteint (429).")
        with patch("scraping.fmp_client._fmp_get", side_effect=raise_rate_limit):
            with pytest.raises(RuntimeError, match="rate limit"):
                get_fmp_data("TEST")

    def test_fmp_exclusive_fields(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")
        assert data.get("ev_ebitda") == pytest.approx(18.0)
        assert data.get("roce") == pytest.approx(0.20)
        assert isinstance(data.get("per_history"), list)
        assert isinstance(data.get("roe_history"), list)

    def test_european_ticker(self):
        """MC.PA doit fonctionner sans transformation du symbole."""
        with _patch_fmp_endpoints():
            data = get_fmp_data("MC.PA")
        assert data["ticker"] == "MC.PA"

    def test_cagr_revenue_computed(self):
        with _patch_fmp_endpoints():
            data = get_fmp_data("TEST")
        # 50B → 100B sur 2 ans ≈ 41% CAGR
        assert data["revenue_cagr_10y"] is not None
        assert data["revenue_cagr_10y"] > 0

    def test_cache_used_on_second_call(self):
        call_count = 0

        def counting_side_effect(path, params=None):
            nonlocal call_count
            call_count += 1
            return _make_fmp_get_side_effect(
                income=list(reversed(INCOME_RECORDS)),
                balance=list(reversed(BALANCE_RECORDS)),
                cashflow=list(reversed(CASHFLOW_RECORDS)),
                metrics=list(reversed(METRICS_RECORDS)),
                profile=[PROFILE],
            )(path, params)

        with patch("scraping.fmp_client._fmp_get", side_effect=counting_side_effect):
            get_fmp_data("CACHED")
            calls_after_first = call_count
            get_fmp_data("CACHED")  # doit utiliser le cache mémoire
            assert call_count == calls_after_first  # aucun appel supplémentaire


# ---------------------------------------------------------------------------
# Tests : merge_yfinance_fmp
# ---------------------------------------------------------------------------

class TestMergeYfinanceFmp:
    def _make_yf(self, revenues=None, roe=None):
        return {
            "source": "yfinance",
            "ticker": "TEST",
            "revenues": revenues or [10, 20, 30],
            "years": [2022, 2023, 2024],
            "gross_profits": [5, 10, 15],
            "operating_incomes": [3, 6, 9],
            "net_incomes": [2, 4, 6],
            "ebitdas": [4, 8, 12],
            "interest_expenses": [1, 1, 1],
            "eps_history": [1, 2, 3],
            "fcf_history": [1, 2, 3],
            "operating_cf_history": [2, 3, 4],
            "capex_history": [1, 1, 1],
            "ebitda": 12,
            "roe": roe,
            "roa": None,
            "revenue_cagr_10y": 0.10,
        }

    def _make_fmp(self, revenues=None, roe=None, roce=None):
        return {
            "source": "fmp",
            "ticker": "TEST",
            "revenues": revenues or [5, 10, 20, 30, 40, 50, 60, 70, 80, 90],
            "years": list(range(2015, 2025)),
            "gross_profits": [None] * 10,
            "operating_incomes": [None] * 10,
            "net_incomes": [None] * 10,
            "ebitdas": [None] * 10,
            "interest_expenses": [None] * 10,
            "eps_history": [None] * 10,
            "fcf_history": [None] * 10,
            "operating_cf_history": [None] * 10,
            "capex_history": [None] * 10,
            "ebitda": 35,
            "roe": roe or 0.25,
            "roa": 0.10,
            "revenue_cagr_10y": 0.12,
            "roce": roce or 0.20,
            "ev_ebitda": 18.0,
            "per_history": [20.0] * 10,
            "ev_ebitda_history": [18.0] * 10,
            "roe_history": [0.25] * 10,
            "roce_history": [0.20] * 10,
        }

    def test_source_becomes_merged(self):
        merged = merge_yfinance_fmp(self._make_yf(), self._make_fmp())
        assert merged["source"] == "merged_yf_fmp"

    def test_fmp_longer_revenue_preferred(self):
        yf = self._make_yf(revenues=[10, 20, 30])
        fmp = self._make_fmp(revenues=list(range(10)))
        merged = merge_yfinance_fmp(yf, fmp)
        assert merged["revenues"] == list(range(10))

    def test_yf_longer_revenue_kept(self):
        yf = self._make_yf(revenues=list(range(10)))
        fmp = self._make_fmp(revenues=[10, 20, 30])
        merged = merge_yfinance_fmp(yf, fmp)
        assert merged["revenues"] == list(range(10))

    def test_none_scalar_filled_from_fmp(self):
        yf = self._make_yf(roe=None)
        fmp = self._make_fmp(roe=0.25)
        merged = merge_yfinance_fmp(yf, fmp)
        assert merged["roe"] == pytest.approx(0.25)

    def test_yf_scalar_not_overwritten(self):
        yf = self._make_yf(roe=0.30)
        fmp = self._make_fmp(roe=0.15)
        merged = merge_yfinance_fmp(yf, fmp)
        assert merged["roe"] == pytest.approx(0.30)  # yfinance conservé

    def test_fmp_exclusive_fields_added(self):
        merged = merge_yfinance_fmp(self._make_yf(), self._make_fmp(roce=0.20))
        assert merged.get("roce") == pytest.approx(0.20)
        assert merged.get("ev_ebitda") == pytest.approx(18.0)
        assert isinstance(merged.get("per_history"), list)

    def test_yf_fields_preserved(self):
        yf = self._make_yf()
        merged = merge_yfinance_fmp(yf, self._make_fmp())
        assert merged["ticker"] == "TEST"
        assert merged["revenue_cagr_10y"] == pytest.approx(0.10)
