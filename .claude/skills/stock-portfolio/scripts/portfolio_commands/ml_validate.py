"""ML validation subcommand: walk-forward, SHAP, Optuna."""

from __future__ import annotations


def execute(args: list[str], yahoo_client_module) -> None:
    """Run ML-enhanced backtest validation.

    Usage:
      ml-validate [--preset PRESET] [--region REGION] [--days DAYS]
                  [--splits N] [--trials N] [--mode MODE]

    Modes:
      all       -- run walk-forward + SHAP + Optuna (default)
      walkfwd   -- walk-forward validation only
      shap      -- SHAP feature importance only
      optuna    -- threshold optimization only
    """
    import argparse
    from src.core.portfolio.ml_backtest import (
        build_ml_dataset,
        run_walk_forward,
        run_shap_analysis,
        run_optuna_optimization,
        HAS_SKLEARN, HAS_SHAP, HAS_OPTUNA,
    )

    parser = argparse.ArgumentParser(prog="ml-validate", add_help=False)
    parser.add_argument("--preset", default=None)
    parser.add_argument("--region", default=None)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--mode", default="all",
                        choices=["all", "walkfwd", "shap", "optuna"])
    parsed = parser.parse_args(args)

    _check_deps(parsed.mode)

    print("\n=== ML Backtest Validation ===")
    print(f"Preset: {parsed.preset or 'all'}  Region: {parsed.region or 'all'}  "
          f"Days: {parsed.days}")
    print("Building dataset from screening history...")

    dataset = build_ml_dataset(
        yahoo_client_module,
        preset=parsed.preset,
        region=parsed.region,
        days_back=parsed.days,
    )

    n = len(dataset["dates"])
    if n == 0:
        print("No data found. Run screen-stocks first to build history.")
        return

    print(f"Loaded {n} samples from {len(set(dataset['dates']))} screening dates.")
    print(f"Baseline win rate: {dataset['y_binary'].mean():.1%}\n")

    if parsed.mode in ("all", "walkfwd"):
        _print_walk_forward(run_walk_forward(dataset, n_splits=parsed.splits))

    if parsed.mode in ("all", "shap"):
        _print_shap(run_shap_analysis(dataset))

    if parsed.mode in ("all", "optuna"):
        print(f"Running Optuna ({parsed.trials} trials)...")
        _print_optuna(run_optuna_optimization(
            dataset, n_trials=parsed.trials, n_splits=min(parsed.splits, 3)
        ))


def _check_deps(mode: str) -> None:
    missing = []
    try:
        import sklearn  # noqa: F401
    except ImportError:
        missing.append("scikit-learn")
    if mode in ("all", "shap"):
        try:
            import shap  # noqa: F401
        except ImportError:
            missing.append("shap")
    if mode in ("all", "optuna"):
        try:
            import optuna  # noqa: F401
        except ImportError:
            missing.append("optuna")

    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        raise SystemExit(1)


def _print_walk_forward(result: dict) -> None:
    print("--- Walk-forward Validation ---")
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    for f in result["folds"]:
        print(f"  Fold {f['fold']} [{f['test_start']} ~ {f['test_end']}]  "
              f"accuracy={f['accuracy']:.1%}  win_rate={f['win_rate']:.1%}  "
              f"avg_return={f['avg_return']:+.1%}")

    print(f"  Average: accuracy={result['avg_accuracy']:.1%}  "
          f"win_rate={result['avg_win_rate']:.1%}  "
          f"avg_return={result['avg_return']:+.1%}")
    print()


def _print_shap(result: dict) -> None:
    print("--- SHAP Feature Importance ---")
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"  Samples: {result['n_samples']}  "
          f"Train accuracy: {result['train_accuracy']:.1%}  "
          f"Baseline win rate: {result['baseline_win_rate']:.1%}")
    print("  Feature importance (mean |SHAP|):")
    for item in result["feature_importances"]:
        bar = "#" * int(item["shap_importance"] * 200)
        print(f"    {item['feature']:20s}  {item['shap_importance']:.4f}  {bar}")
    print()


def _print_optuna(result: dict) -> None:
    print("--- Optuna Threshold Optimization ---")
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"  Samples: {result['n_samples']}  Trials: {result['n_trials']}")
    print(f"  Default avg return:  {result['default_avg_return']:+.1%}")
    print(f"  Optimized avg return:{result['best_avg_return']:+.1%}  "
          f"(improvement: {result['improvement']:+.1%})")
    print("  Best parameters:")
    defaults = result["default_params"]
    for k, v in result["best_params"].items():
        default_v = defaults.get(k, "?")
        print(f"    {k:12s}: {v:.4f}  (default: {default_v})")
    print()
