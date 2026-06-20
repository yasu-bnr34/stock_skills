# CHANGELOG

このプロジェクトの主要な変更履歴。

## 2026-06-21 — Windows対応・WIP整理・横断記憶 (yasu-bnr34 fork)

CAD server (Windows 11) 環境での整理セッション。溜まっていた未コミットWIP（18ファイル変更・764行）を機能別に分割し、Windows固有の不具合を修正。

### 追加 (Added)
- **ML検証**: walk-forward / SHAP / Optuna バックテスト検証（`src/core/portfolio/ml_backtest.py`, `ml-validate` サブコマンド）
- **リアルタイム取得**: 急騰株/Grokトレンド取得スクリプト（`scripts/fetch_yahoo_realtime.py`, `scripts/fetch_grok_trending.py`）
- **lesson強化**: lesson_rules生成・noteテーマ集約（`generate_lesson_rules.py`, `note_manager.aggregate_lessons_by_theme`）
- **スクリーニング**: surgeプリセット（当日急騰株）+ テクニカル指標拡張（Stochastics/DMI/MA乖離率）
- **横断記憶**: `AGENTS.md`（Codex/Cursor共通エントリポイント）, `PROJECT.md`

### 修正 (Fixed)
- **Windows: タイムアウト処理** — `scripts/common.py` の `signal.SIGALRM`（Unix専用）をクロスプラットフォーム化（Unix=SIGALRM維持 / Windows=デーモンスレッド）。テスト失敗6件を解消。
- **Windows: ドキュメント生成** — `generate_docs.py` がバックスラッシュパスとYAMLキー（`/`）を誤照合し、再生成のたびにKIKアノテーションが消える問題を `Path.as_posix()` で修正。`api-reference.md` 再生成。

### セキュリティ・整理 (Security / Chore)
- `.claude/settings.json` から **XAI APIキー直書きを除去**（`.env` へ集約。`.env`はgitignore済）
- macOS専用テストフック（`/Users/kikuchihiroyuki/...`）を削除
- 生成データ（`data/yahoo_realtime/`, `data/grok_trending/`, `data/lesson_rules.json`）を gitignore 化
- キャッシュ整理: `__pycache__`/`.pytest_cache`/`.omc` を ignore、`.DS_Store` 追跡解除

### 検証 (Verified)
- 全 **3324 テスト通過**（Windows, pytest）

> 備考: この更新は fork `yasu-bnr34/stock_skills` に push 済み。upstream `okikusan-public/stock_skills`（菊池氏所有）へは書き込み権限がないため、反映する場合は Pull Request を使用する。
