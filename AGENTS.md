# AGENTS.md — stock_skills

> このファイルは Codex / Cursor / その他 AI ツール共通のエントリポイントです。
> このプロジェクトは Claude Code Skills 前提で設計されており、
> **本体ドキュメントは `CLAUDE.md` と `.claude/rules/` 配下にあります。**
> 全ツールで同じ文脈を共有するため、作業前に下記を必ず読んでください。

## 作業開始時に必ず読むもの（順番厳守）

1. `CLAUDE.md` — 設計思想（自然言語ファースト）・プロジェクト概要・アーキテクチャ
2. `README.md` / `PROJECT.md` — 全体像
3. `.claude/rules/` — 開発・運用ルール（**ここが知識の本体**）
   - `development.md` — 言語/依存/コーディング規約/テスト/ファイル構成
   - `intent-routing.md` — 自然言語→スキルのルーティング表
   - `graph-context.md` — Neo4jスキーマ + 自動コンテキスト注入
   - `workflow.md` — Worktree開発フロー（設計→実装→テスト→レビュー→結合試験）
   - `plan-check.md` — 投資判断マルチエージェントフロー
4. `docs/` — architecture / neo4j-schema / skill-catalog / data-models / api-reference

## プロジェクト概要

- **役割**: 割安株スクリーニングシステム（日本株・米国株・ASEAN等60地域）
- **動作形態**: Claude Code Skills。自然言語で話しかけると適切なスキルが自動実行される
- **スタック**: Python 3.10+ / yfinance / Neo4j(view) / pytest（約3287テスト）
- **スキル一覧**: screen-stocks / stock-report / market-research / stock-portfolio /
  stress-test / watchlist / investment-note / graph-query / plan-execute

## Codex / Cursor 利用時の注意

- `/screen-stocks` 等のスラッシュコマンドは **Claude Code Skills の内部実装**です。
  Codex/Cursor から直接スキルは起動できないため、対応する Python スクリプトを直接実行してください。
  例: `python3 .claude/skills/screen-stocks/scripts/run_screen.py --region japan --preset value --top 10`
- 自然言語→スクリプトの対応は `.claude/rules/intent-routing.md` を参照。

---

## 共通コーディングルール（全AIツール共通）

### Python ファイルI/O — encoding を必ず明示する
- UTF-8ファイル → `encoding='utf-8'`
- Shift-JIS / 古いExcel・CSV → `encoding='cp932'`
- 理由: Windows のデフォルトエンコーディングは読み書きで静かにデータ破損を起こす
- ※ プロジェクト固有規約（yahoo_client経由必須・HAS_MODULEパターン等）は `.claude/rules/development.md` が優先

### .bat ファイルのテキストはすべて英語で書く
- コメント・echo・変数名・メッセージすべて英語
- 理由: CMD.exe は .bat を CP932 で読むため、UTF-8 日本語はパースエラー・文字化けになる

### ローカルLLM / Grok を扱う場合
- ローカルLLM構成は `C:\Users\CAD server\Documents\cursor\local_llm\PC_list.txt` を参照
- Grok等のAPIキーは環境変数（`XAI_API_KEY` 等）で管理。コミット・外部送信しない

---

## ナレッジの残し方（横断記憶）

- このプロジェクトの確定知識は `.claude/rules/` と `docs/` に集約する（ai_wiki は未使用）
- 機能追加・変更時は `.claude/rules/workflow.md` の「7. ドキュメント・ルール更新」に従う
- ここに残した知見は、別のAIツール（Claude / Codex / Cursor）に切り替えても引き継がれる
