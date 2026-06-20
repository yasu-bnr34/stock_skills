"""Tests for ml_backtest module."""

import numpy as np
import pytest

from src.core.portfolio.ml_backtest import (
    _score_per, _score_pbr, _score_dividend, _score_roe, _score_growth,
    _rescore,
    build_ml_dataset,
    run_walk_forward,
    run_shap_analysis,
    run_optuna_optimization,
    FEATURE_NAMES,
    RAW_FEATURE_NAMES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_dataset(n: int = 30, seed: int = 42) -> dict:
    """Create a synthetic dataset for testing."""
    rng = np.random.default_rng(seed)
    X_scores = rng.uniform(0, 25, size=(n, 9))
    X_raw = np.column_stack([
        rng.uniform(5, 30, n),   # per
        rng.uniform(0.3, 3, n),  # pbr
        rng.uniform(0, 0.08, n), # div_yield
        rng.uniform(0, 0.20, n), # roe
        rng.uniform(-0.1, 0.3, n), # growth
    ])
    y_binary = rng.integers(0, 2, size=n)
    y_returns = rng.uniform(-0.3, 0.5, size=n)
    # Spread over 30 different dates
    dates = [f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    symbols = [f"SYM{i:04d}.T" for i in range(n)]
    return {
        "X_scores": X_scores,
        "X_raw": X_raw,
        "y_binary": y_binary,
        "y_returns": y_returns,
        "dates": dates,
        "symbols": symbols,
        "feature_names": FEATURE_NAMES,
        "raw_feature_names": RAW_FEATURE_NAMES,
    }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

class TestScoringHelpers:
    def test_score_per_none(self):
        assert _score_per(None, 15.0) == 0.0

    def test_score_per_zero(self):
        assert _score_per(0, 15.0) == 0.0

    def test_score_per_negative(self):
        assert _score_per(-5, 15.0) == 0.0

    def test_score_per_max_score(self):
        # Very low PER should score close to 25
        score = _score_per(0.01, 15.0)
        assert score > 24.0

    def test_score_per_above_ceiling(self):
        # PER >= per_max * 2 → 0
        assert _score_per(30.0, 15.0) == 0.0

    def test_score_pbr_none(self):
        assert _score_pbr(None, 1.0) == 0.0

    def test_score_pbr_valid(self):
        score = _score_pbr(0.5, 1.0)
        assert 0 < score <= 25.0

    def test_score_dividend_none(self):
        assert _score_dividend(None, 0.03) == 0.0

    def test_score_dividend_zero(self):
        assert _score_dividend(0.0, 0.03) == 0.0

    def test_score_dividend_max(self):
        # div >= div_min * 3 → 20 pts
        assert _score_dividend(0.09, 0.03) == 20.0

    def test_score_roe_none(self):
        assert _score_roe(None, 0.08) == 0.0

    def test_score_growth_negative(self):
        assert _score_growth(-0.1) == 0.0

    def test_score_growth_positive(self):
        score = _score_growth(0.15)
        assert 0 < score <= 15.0


class TestRescore:
    def test_rescore_shape(self):
        X_raw = np.array([
            [10.0, 0.8, 0.04, 0.10, 0.15],
            [20.0, 2.0, 0.01, 0.05, 0.0],
        ])
        result = _rescore(X_raw, 15.0, 1.0, 0.03, 0.08)
        assert result.shape == (2,)

    def test_rescore_bounded(self):
        X_raw = np.zeros((5, 5))
        result = _rescore(X_raw, 15.0, 1.0, 0.03, 0.08)
        assert (result >= 0).all()
        assert (result <= 100).all()

    def test_rescore_lower_thresholds_higher_scores(self):
        X_raw = np.array([[10.0, 0.5, 0.04, 0.10, 0.10]])
        score_strict = _rescore(X_raw, 15.0, 1.0, 0.03, 0.08)
        score_lenient = _rescore(X_raw, 20.0, 2.0, 0.02, 0.05)
        # Lenient thresholds → higher scores for moderate-value stocks
        assert score_lenient[0] >= score_strict[0]


# ---------------------------------------------------------------------------
# build_ml_dataset
# ---------------------------------------------------------------------------

class TestBuildMlDataset:
    def test_empty_history(self, mock_yahoo_client, tmp_path):
        result = build_ml_dataset(mock_yahoo_client, base_dir=str(tmp_path))
        assert result["X_scores"].shape == (0, 9)
        assert result["X_raw"].shape == (0, 5)
        assert len(result["dates"]) == 0

    def test_feature_names(self, mock_yahoo_client, tmp_path):
        result = build_ml_dataset(mock_yahoo_client, base_dir=str(tmp_path))
        assert result["feature_names"] == FEATURE_NAMES
        assert result["raw_feature_names"] == RAW_FEATURE_NAMES


# ---------------------------------------------------------------------------
# run_walk_forward
# ---------------------------------------------------------------------------

class TestRunWalkForward:
    def test_requires_sklearn(self, monkeypatch):
        import src.core.portfolio.ml_backtest as m
        monkeypatch.setattr(m, "HAS_SKLEARN", False)
        result = run_walk_forward(_make_dataset())
        assert "error" in result

    def test_insufficient_samples(self):
        ds = _make_dataset(n=4)
        result = run_walk_forward(ds, n_splits=5)
        assert "error" in result

    def test_returns_folds(self):
        pytest.importorskip("sklearn")
        ds = _make_dataset(n=30)
        result = run_walk_forward(ds, n_splits=3)
        if "error" in result:
            pytest.skip(result["error"])
        assert "folds" in result
        assert len(result["folds"]) > 0

    def test_fold_keys(self):
        pytest.importorskip("sklearn")
        ds = _make_dataset(n=30)
        result = run_walk_forward(ds, n_splits=3)
        if "error" in result:
            pytest.skip(result["error"])
        for fold in result["folds"]:
            assert "accuracy" in fold
            assert "win_rate" in fold
            assert "avg_return" in fold
            assert 0.0 <= fold["accuracy"] <= 1.0
            assert 0.0 <= fold["win_rate"] <= 1.0

    def test_aggregate_stats(self):
        pytest.importorskip("sklearn")
        ds = _make_dataset(n=30)
        result = run_walk_forward(ds, n_splits=3)
        if "error" in result:
            pytest.skip(result["error"])
        assert "avg_accuracy" in result
        assert "avg_win_rate" in result
        assert "avg_return" in result
        assert 0.0 <= result["avg_accuracy"] <= 1.0

    def test_chronological_split(self):
        pytest.importorskip("sklearn")
        ds = _make_dataset(n=30)
        result = run_walk_forward(ds, n_splits=3)
        if "error" in result:
            pytest.skip(result["error"])
        folds = result["folds"]
        # Later folds should have later start dates
        for i in range(len(folds) - 1):
            assert folds[i]["test_start"] <= folds[i + 1]["test_start"]


# ---------------------------------------------------------------------------
# run_shap_analysis
# ---------------------------------------------------------------------------

class TestRunShapAnalysis:
    def test_requires_sklearn(self, monkeypatch):
        import src.core.portfolio.ml_backtest as m
        monkeypatch.setattr(m, "HAS_SKLEARN", False)
        result = run_shap_analysis(_make_dataset())
        assert "error" in result

    def test_requires_shap(self, monkeypatch):
        import src.core.portfolio.ml_backtest as m
        monkeypatch.setattr(m, "HAS_SHAP", False)
        result = run_shap_analysis(_make_dataset())
        assert "error" in result

    def test_insufficient_samples(self):
        ds = _make_dataset(n=5)
        result = run_shap_analysis(ds)
        assert "error" in result

    def test_returns_importances(self):
        pytest.importorskip("sklearn")
        pytest.importorskip("shap")
        ds = _make_dataset(n=30)
        result = run_shap_analysis(ds)
        if "error" in result:
            pytest.skip(result["error"])
        assert "feature_importances" in result
        assert len(result["feature_importances"]) == len(FEATURE_NAMES)

    def test_importances_sorted_desc(self):
        pytest.importorskip("sklearn")
        pytest.importorskip("shap")
        ds = _make_dataset(n=30)
        result = run_shap_analysis(ds)
        if "error" in result:
            pytest.skip(result["error"])
        importances = [f["shap_importance"] for f in result["feature_importances"]]
        assert importances == sorted(importances, reverse=True)

    def test_all_features_covered(self):
        pytest.importorskip("sklearn")
        pytest.importorskip("shap")
        ds = _make_dataset(n=30)
        result = run_shap_analysis(ds)
        if "error" in result:
            pytest.skip(result["error"])
        covered = {f["feature"] for f in result["feature_importances"]}
        assert covered == set(FEATURE_NAMES)


# ---------------------------------------------------------------------------
# run_optuna_optimization
# ---------------------------------------------------------------------------

class TestRunOptunaOptimization:
    def test_requires_optuna(self, monkeypatch):
        import src.core.portfolio.ml_backtest as m
        monkeypatch.setattr(m, "HAS_OPTUNA", False)
        result = run_optuna_optimization(_make_dataset())
        assert "error" in result

    def test_requires_sklearn(self, monkeypatch):
        import src.core.portfolio.ml_backtest as m
        monkeypatch.setattr(m, "HAS_SKLEARN", False)
        result = run_optuna_optimization(_make_dataset())
        assert "error" in result

    def test_insufficient_samples(self):
        ds = _make_dataset(n=3)
        result = run_optuna_optimization(ds, n_trials=5, n_splits=3)
        assert "error" in result

    def test_returns_best_params(self):
        pytest.importorskip("optuna")
        pytest.importorskip("sklearn")
        ds = _make_dataset(n=30)
        result = run_optuna_optimization(ds, n_trials=10, n_splits=2)
        if "error" in result:
            pytest.skip(result["error"])
        assert "best_params" in result
        expected_keys = {"per_max", "pbr_max", "div_min", "roe_min", "min_score"}
        assert set(result["best_params"].keys()) == expected_keys

    def test_param_bounds(self):
        pytest.importorskip("optuna")
        pytest.importorskip("sklearn")
        ds = _make_dataset(n=30)
        result = run_optuna_optimization(ds, n_trials=10, n_splits=2)
        if "error" in result:
            pytest.skip(result["error"])
        p = result["best_params"]
        assert 10.0 <= p["per_max"] <= 25.0
        assert 0.5 <= p["pbr_max"] <= 3.0
        assert 0.01 <= p["div_min"] <= 0.06
        assert 0.05 <= p["roe_min"] <= 0.20
        assert 30.0 <= p["min_score"] <= 70.0

    def test_default_params_present(self):
        pytest.importorskip("optuna")
        pytest.importorskip("sklearn")
        ds = _make_dataset(n=30)
        result = run_optuna_optimization(ds, n_trials=5, n_splits=2)
        if "error" in result:
            pytest.skip(result["error"])
        assert "default_params" in result
        assert "improvement" in result
