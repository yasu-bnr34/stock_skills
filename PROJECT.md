# StockMind — AI投資分析システム

自然言語で話しかけるだけで株式分析・ポートフォリオ管理ができる個人用AIアシスタント。

## セットアップ済み環境

| コンポーネント | 詳細 |
|---|---|
| リポジトリ | `C:\Users\CAD server\Documents\cursor\stock_skills` |
| Python | 3.12.10 |
| Neo4j | `localhost:7688`（Docker、自動起動） |
| Embeddingサービス | `localhost:8081`（Docker、自動起動） |
| データソース | Yahoo Finance（無料） |
| AIエンジン | Claude Code + Grok API |

## 使い方

Claude Codeで `stock_skills` フォルダを開いて日本語で話しかける。

```
「いい日本株ある？」         → 割安株スクリーニング（60地域対応）
「トヨタってどう？」         → 個別銘柄レポート
「トヨタの最新ニュースは？」   → Grok APIで深掘りリサーチ
「PF大丈夫かな」            → ポートフォリオヘルスチェック
「暴落したらどうなる？」      → ストレステスト
「気になるから記録して」      → ウォッチリスト管理
「投資メモを残して」         → 投資テーゼ・学び記録
「前回調べた銘柄は？」        → 知識グラフ検索
```

## Docker管理

```bash
# 起動（PC再起動後、Docker Desktopが立ち上がれば自動起動）
cd "C:\Users\CAD server\Documents\cursor\stock_skills"
docker compose up -d

# 停止
docker compose down

# 状態確認
docker ps
```

## 主要ファイル

| ファイル | 内容 |
|---|---|
| `.claude/settings.json` | 環境変数（APIキー等） |
| `docker-compose.yml` | Neo4j + Embeddingサービス定義 |
| `requirements.txt` | Python依存パッケージ |
| `.claude/skills/` | 9つの分析スキル |
| `src/` | コアロジック |
| `data/` | キャッシュ・ウォッチリスト・メモ（gitignore） |
| `AGENTS.md` | Codex/Cursor共通エントリポイント（横断記憶のハブ） |
| `CHANGELOG.md` | 主要な変更履歴 |

## Git リモート構成

| remote | URL | 用途 |
|---|---|---|
| `origin` | `okikusan-public/stock_skills`（菊池氏） | upstream。**書き込み権限なし**（読み取りのみ） |
| `fork` | `yasu-bnr34/stock_skills`（鈴木） | push先。ローカル`main`が`fork/main`を追跡 |

- 日常の `git push` は **fork** へ飛ぶ。認証はGCM（Windows資格情報マネージャー）に保存済みで再プロンプトなし。
- upstream へ反映する場合は fork から **Pull Request** を作成する。

## Windows環境での注意（2026-06-21対応済み）

- このリポジトリは元々 macOS で開発（`/Users/kikuchihiroyuki/...`）。Windows固有の不具合を修正済み:
  - `scripts/common.py` のタイムアウト: `signal.SIGALRM`(Unix専用) → クロスプラットフォーム化
  - `scripts/generate_docs.py`: パス照合を `Path.as_posix()` に統一（KIKアノテーション消失バグ修正）
- 全3324テスト通過（Windows）。詳細は `CHANGELOG.md` 参照。
