"""ML-enhanced backtest: Walk-forward validation, SHAP, Optuna.

Adds three validation layers on top of the rule-based screening system:
  1. Walk-forward validation (TimeSeriesSplit) -- overfitting prevention
  2. SHAP feature importance -- which indicators drive positive returns
  3. Optuna threshold optimization -- auto-tune per_max, pbr_max, etc.

Note: Features are computed from *current* financial data for historically
screened symbols. This is a simplification; ideally point-in-time data
would be used.
"""

from __future__ import annotations

import numpy as np

try:
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

from src.data.history import load_history
from src.core.screening.alpha import compute_change_score


FEATURE_NAMES = [
    "per_score", "pbr_score", "div_score", "roe_score", "growth_score",
    "accruals_score", "rev_accel_score", "fcf_yield_score", "roe_trend_score",
]
RAW_FEATURE_NAMES = ["per", "pbr", "div_yield", "roe", "revenue_growth"]


# ---------------------------------------------------------------------------
# Internal scoring helpers (duplicated to allow threshold variation in Optuna)
# ---------------------------------------------------------------------------

def _score_per(per, per_max: float) -> float:
    if per is None or per <= 0 or per >= per_max * 2:
        return 0.0
    return max(0.0, 25.0 * (1.0 - per / (per_max * 2)))


def _score_pbr(pbr, pbr_max: float) -> float:
    if pbr is None or pbr <= 0 or pbr >= pbr_max * 2:
        return 0.0
    return max(0.0, 25.0 * (1.0 - pbr / (pbr_max * 2)))


def _score_dividend(div, div_min: float) -> float:
    if div is None or div <= 0:
        return 0.0
    return 20.0 * min(div / (div_min * 3), 1.0)


def _score_roe(roe, roe_min: float) -> float:
    if roe is None or roe <= 0:
        return 0.0
    return 15.0 * min(roe / (roe_min * 3), 1.0)


def _score_growth(growth) -> float:
    if growth is None or growth <= 0:
        return 0.0
    return 15.0 * min(growth / 0.30, 1.0)


def _rescore(X_raw: np.ndarray, per_max: float, pbr_max: float,
             div_min: float, roe_min: float) -> np.ndarray:
    """Re-compute value scores for raw feature matrix with given thresholds."""
    scores = np.zeros(len(X_raw))
    for i, (per, pbr, div, roe, growth) in enumerate(X_raw):
        s = (
            _score_per(per, per_max)
            + _score_pbr(pbr, pbr_max)
            + _score_dividend(div, div_min)
            + _score_roe(roe, roe_min)
            + _score_growth(growth)
        )
        scores[i] = min(s, 100.0)
    return scores


# ---------------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------------

def build_ml_dataset(
    yahoo_client_module,
    category: str = "screen",
    preset: str | None = None,
    region: str | None = None,
    days_back: int = 365,
    base_dir: str = "data/history",
) -> dict:
    """Build feature matrix and return labels from screening history.

    Returns dict with keys:
      X_scores  -- np.ndarray (n, 9): component scores with default thresholds
      X_raw     -- np.ndarray (n, 5): raw financial values for Optuna re-scoring
      y_binary  -- np.ndarray (n,): 1 if return > 0, else 0
      y_returns -- np.ndarray (n,): actual return ratio
      dates     -- list[str]: screen_date per sample (for time-based split)
      symbols   -- list[str]
      feature_names     -- list[str]
      raw_feature_names -- list[str]
    """
    history = load_history(category, days_back=days_back, base_dir=base_dir)
    if preset:
        history = [h for h in history if h.get("preset") == preset]
    if region:
        history = [h for h in history if h.get("region") == region]

    # Keep earliest record per symbol
    seen: dict[str, dict] = {}
    for record in history:
        screen_date = record.get("date", "")
        for stock in record.get("results", []):
            symbol = stock.get("symbol")
            price = stock.get("price")
            if not symbol or not price or price <= 0:
                continue
            if symbol not in seen or screen_date < seen[symbol]["screen_date"]:
                seen[symbol] = {
                    "symbol": symbol,
                    "screen_date": screen_date,
                    "price_at_screen": float(price),
                }

    X_scores, X_raw, y_binary, y_returns, dates, symbols = [], [], [], [], [], []

    for entry in seen.values():
        symbol = entry["symbol"]

        info = yahoo_client_module.get_stock_info(symbol)
        if info is None:
            continue
        price_now = info.get("price")
        if not price_now or price_now <= 0:
            continue

        ret = (float(price_now) - entry["price_at_screen"]) / entry["price_at_screen"]

        # Raw financial values
        per = info.get("trailingPE") or info.get("per") or 0.0
        pbr = info.get("priceToBook") or info.get("pbr") or 0.0
        div = (info.get("dividend_yield_trailing")
               or info.get("dividendYield")
               or info.get("dividend_yield") or 0.0)
        roe = info.get("returnOnEquity") or info.get("roe") or 0.0
        growth = info.get("revenueGrowth") or info.get("revenue_growth") or 0.0

        # Component scores with default thresholds
        per_s = _score_per(per, 15.0)
        pbr_s = _score_pbr(pbr, 1.0)
        div_s = _score_dividend(div, 0.03)
        roe_s = _score_roe(roe, 0.08)
        growth_s = _score_growth(growth)

        # Change score components (alpha.py)
        try:
            detail = yahoo_client_module.get_stock_detail(symbol)
        except Exception:
            detail = None
        cs = compute_change_score(detail or info)

        X_scores.append([
            per_s, pbr_s, div_s, roe_s, growth_s,
            cs["accruals"]["score"],
            cs["revenue_acceleration"]["score"],
            cs["fcf_yield"]["score"],
            cs["roe_trend"]["score"],
        ])
        X_raw.append([per, pbr, div, roe, growth])
        y_binary.append(1 if ret > 0 else 0)
        y_returns.append(ret)
        dates.append(entry["screen_date"])
        symbols.append(symbol)

    n = len(X_scores)
    return {
        "X_scores": np.array(X_scores) if n else np.zeros((0, 9)),
        "X_raw": np.array(X_raw) if n else np.zeros((0, 5)),
        "y_binary": np.array(y_binary, dtype=int),
        "y_returns": np.array(y_returns, dtype=float),
        "dates": dates,
        "symbols": symbols,
        "feature_names": FEATURE_NAMES,
        "raw_feature_names": RAW_FEATURE_NAMES,
    }


# ---------------------------------------------------------------------------
# 1. Walk-forward validation
# ---------------------------------------------------------------------------

def run_walk_forward(dataset: dict, n_splits: int = 5) -> dict:
    """Walk-forward validation via TimeSeriesSplit.

    Sorts samples by screen_date, trains RandomForest on past data,
    evaluates on unseen future data for each fold.

    Returns per-fold metrics and aggregate averages.
    """
    if not HAS_SKLEARN:
        return {"error": "sklearn not installed. Run: pip install scikit-learn"}

    X = dataset["X_scores"]
    y = dataset["y_binary"]
    returns = dataset["y_returns"]
    dates = dataset["dates"]

    if len(X) < n_splits * 2:
        return {
            "error": f"Not enough samples ({len(X)}) for {n_splits} splits. "
                     f"Need at least {n_splits * 2}."
        }

    # Sort chronologically
    order = sorted(range(len(dates)), key=lambda i: dates[i])
    X = X[order]
    y = y[order]
    returns = returns[order]
    sorted_dates = [dates[i] for i in order]

    tscv = TimeSeriesSplit(n_splits=n_splits)
    folds = []

    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        ret_test = returns[test_idx]

        if len(set(y_train)) < 2:
            continue

        model = RandomForestClassifier(n_estimators=50, random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        folds.append({
            "fold": fold_idx + 1,
            "train_size": int(len(train_idx)),
            "test_size": int(len(test_idx)),
            "test_start": sorted_dates[test_idx[0]],
            "test_end": sorted_dates[test_idx[-1]],
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "win_rate": round(float(y_test.mean()), 4),
            "avg_return": round(float(ret_test.mean()), 4),
            "model_win_rate": round(float(y_pred.mean()), 4),
        })

    if not folds:
        return {"error": "No valid folds produced (possibly all-same-class in train set)"}

    return {
        "n_splits": n_splits,
        "total_samples": int(len(X)),
        "folds": folds,
        "avg_accuracy": round(float(np.mean([f["accuracy"] for f in folds])), 4),
        "avg_win_rate": round(float(np.mean([f["win_rate"] for f in folds])), 4),
        "avg_return": round(float(np.mean([f["avg_return"] for f in folds])), 4),
    }


# ---------------------------------------------------------------------------
# 2. SHAP feature importance
# ---------------------------------------------------------------------------

def run_shap_analysis(dataset: dict) -> dict:
    """Compute SHAP values to identify which indicators drive positive returns.

    Trains a RandomForest on the full dataset, then uses TreeExplainer
    to compute mean absolute SHAP values per feature.

    Returns features ranked by importance.
    """
    if not HAS_SKLEARN:
        return {"error": "sklearn not installed. Run: pip install scikit-learn"}
    if not HAS_SHAP:
        return {"error": "shap not installed. Run: pip install shap"}

    X = dataset["X_scores"]
    y = dataset["y_binary"]
    feature_names = dataset["feature_names"]

    if len(X) < 10:
        return {"error": f"Not enough samples ({len(X)}) for SHAP. Need at least 10."}

    model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
    model.fit(X, y)

    explainer = shap.TreeExplainer(model)
    shap_raw = explainer.shap_values(X)

    # Handle different SHAP output shapes:
    #   older SHAP: list [class0(n,f), class1(n,f)]
    #   newer SHAP: ndarray (n, f, n_classes)
    if isinstance(shap_raw, list):
        sv = shap_raw[1]
    elif isinstance(shap_raw, np.ndarray) and shap_raw.ndim == 3:
        sv = shap_raw[:, :, 1]
    else:
        sv = shap_raw

    mean_abs = np.abs(sv).mean(axis=0).flatten()
    pairs = [(name, float(imp)) for name, imp in zip(feature_names, mean_abs)]
    ranked = sorted(pairs, key=lambda x: x[1], reverse=True)

    return {
        "feature_importances": [
            {"feature": name, "shap_importance": round(float(imp), 4)}
            for name, imp in ranked
        ],
        "n_samples": int(len(X)),
        "train_accuracy": round(float(np.mean(model.predict(X) == y)), 4),
        "baseline_win_rate": round(float(y.mean()), 4),
    }


# ---------------------------------------------------------------------------
# 3. Optuna threshold optimization
# ---------------------------------------------------------------------------

def run_optuna_optimization(
    dataset: dict,
    n_trials: int = 50,
    n_splits: int = 3,
) -> dict:
    """Optimize value-score thresholds using Optuna.

    Parameters optimized:
      per_max   -- PER upper bound for full score (default 15.0)
      pbr_max   -- PBR upper bound for full score (default 1.0)
      div_min   -- minimum dividend yield for scoring (default 0.03)
      roe_min   -- minimum ROE for scoring (default 0.08)
      min_score -- minimum value_score to include a stock (default 50.0)

    Objective: maximize average return of stocks passing min_score filter,
    evaluated on walk-forward test folds.
    """
    if not HAS_OPTUNA:
        return {"error": "optuna not installed. Run: pip install optuna"}
    if not HAS_SKLEARN:
        return {"error": "sklearn not installed. Run: pip install scikit-learn"}

    X_raw = dataset["X_raw"]
    returns = dataset["y_returns"]
    dates = dataset["dates"]

    if len(X_raw) < n_splits * 2:
        return {
            "error": f"Not enough samples ({len(X_raw)}) for optimization. "
                     f"Need at least {n_splits * 2}."
        }

    order = sorted(range(len(dates)), key=lambda i: dates[i])
    X_raw_sorted = X_raw[order]
    returns_sorted = returns[order]

    tscv = TimeSeriesSplit(n_splits=n_splits)
    splits = list(tscv.split(X_raw_sorted))

    def objective(trial) -> float:
        per_max = trial.suggest_float("per_max", 10.0, 25.0)
        pbr_max = trial.suggest_float("pbr_max", 0.5, 3.0)
        div_min = trial.suggest_float("div_min", 0.01, 0.06)
        roe_min = trial.suggest_float("roe_min", 0.05, 0.20)
        min_score = trial.suggest_float("min_score", 30.0, 70.0)

        fold_returns = []
        for _, test_idx in splits:
            scores = _rescore(X_raw_sorted[test_idx], per_max, pbr_max, div_min, roe_min)
            mask = scores >= min_score
            if mask.sum() == 0:
                fold_returns.append(-0.1)
                continue
            fold_returns.append(float(returns_sorted[test_idx][mask].mean()))

        return float(np.mean(fold_returns))

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    default_params = {
        "per_max": 15.0, "pbr_max": 1.0,
        "div_min": 0.03, "roe_min": 0.08, "min_score": 50.0,
    }

    # Evaluate default params for comparison
    default_returns = []
    for _, test_idx in splits:
        scores = _rescore(X_raw_sorted[test_idx], **{k: v for k, v in default_params.items() if k != "min_score"})
        mask = scores >= default_params["min_score"]
        if mask.sum() == 0:
            default_returns.append(-0.1)
            continue
        default_returns.append(float(returns_sorted[test_idx][mask].mean()))
    default_score = float(np.mean(default_returns)) if default_returns else 0.0

    return {
        "best_params": {k: round(v, 4) for k, v in study.best_params.items()},
        "best_avg_return": round(study.best_value, 4),
        "default_params": default_params,
        "default_avg_return": round(default_score, 4),
        "improvement": round(study.best_value - default_score, 4),
        "n_trials": n_trials,
        "n_samples": int(len(X_raw)),
    }
