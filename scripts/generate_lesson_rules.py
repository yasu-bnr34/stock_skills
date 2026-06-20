"""
Generate lesson_rules.json from stock_skills/data/notes/*.json.
Filters out generic AI commentary and keeps concrete actionable rules.
Run: python3 scripts/generate_lesson_rules.py
"""
import json
import re
from pathlib import Path

NOTES_DIR = Path(__file__).parent.parent / "data" / "notes"
OUTPUT = Path(__file__).parent.parent / "data" / "lesson_rules.json"

# Patterns that indicate a concrete, actionable rule
USEFUL_PATTERNS = [
    r"\bif\b.*\b(rsi|signal|action|price|ma|macd|stoch)\b",
    r"\bCOOLDOWN\b",
    r"\bMAX_[A-Z_]+\s*=",
    r"signal\s*=\s*['\"]",
    r"[0-9]+\s*(分|時間|%|株)",
    r"(損切り|利確|集中|往復|クールダウン|上限|制限).{0,20}(ルール|基準|設定|禁止|防止)",
    r"(勝率|損益).{0,20}(低|改善|原因)",
    r"1銘柄.{0,30}(以内|上限|制限)",
]

# Patterns to exclude (generic commentary or system-level advice unrelated to trade decisions)
NOISE_PATTERNS = [
    r"外部AI意見: (RSI|Bollinger|MACD|チャート|テクニカル|支え|逆支え|チャンネル|市場|経済|評価|テスト|戦略の調整は|アドバイスの選択|戦略の見直し).{0,30}(することができます|ことが重要です|把握|予測|活用|分析)",
    r"(外部AI意見: )+.{0,50}(可能性があります|プロセスです|必要があります)$",
    r"外部AI意見: (支え|逆支え|チャンネル):",
    r"(ポーリング|トークン|監視銘柄数|IN=|OUT=|5\s*分間|5\s*分ごと|interval|API呼び出し)",
    r"(スクリーニング学習:).{0,30}(監視|ポーリング|トークン|IN=|全株チェック|イベントドリブン)",
]

THEME_KEYWORDS = {
    "exit": ["損切り", "利確", "売り", "SELL", "exit", "エグジット", "stop", "profit"],
    "risk": ["集中", "リスク", "上限", "制限", "サイズ", "MAX_", "COOLDOWN", "往復", "クールダウン"],
    "entry": ["BUY", "買い", "RSI", "エントリー", "signal", "if rsi", "if ma", "ゴールデン"],
}


def is_useful(trigger: str) -> bool:
    for pat in NOISE_PATTERNS:
        if re.search(pat, trigger):
            return False
    for pat in USEFUL_PATTERNS:
        if re.search(pat, trigger, re.IGNORECASE):
            return True
    return False


def classify_theme(trigger: str) -> str:
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in trigger for kw in keywords):
            return theme
    return "risk"


def truncate(text: str, max_len: int = 60) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def main():
    if not NOTES_DIR.exists():
        print(f"Notes directory not found: {NOTES_DIR}")
        return

    themes: dict[str, list[str]] = {"exit": [], "risk": [], "entry": []}
    seen: set[str] = set()

    for notes_file in sorted(NOTES_DIR.glob("*_lesson.json"), reverse=True):
        try:
            items = json.loads(notes_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Skip {notes_file.name}: {e}")
            continue

        for item in items:
            trigger = item.get("trigger", "")
            if not trigger or not is_useful(trigger):
                continue
            rule = truncate(trigger.replace("改善ルール: ", "").replace("外部AI意見: ", "").strip())
            if rule in seen:
                continue
            seen.add(rule)
            theme = classify_theme(trigger)
            themes[theme].append(rule)

    # Limit per theme to avoid prompt bloat
    for key in themes:
        themes[key] = themes[key][:10]

    total = sum(len(v) for v in themes.values())
    prompt_lines = ["【過去lessonの改善ルール】"]
    label_map = {"exit": "エグジット", "risk": "リスク管理", "entry": "エントリー"}
    for key, label in label_map.items():
        rules = themes[key]
        if rules:
            prompt_lines.append(f"[{label}] " + " / ".join(rules[:3]))

    result = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "total_rules": total,
        "prompt_context": "\n".join(prompt_lines),
        "themes": {k: {"proposals": v} for k, v in themes.items()},
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {OUTPUT} — {total} rules (exit:{len(themes['exit'])} risk:{len(themes['risk'])} entry:{len(themes['entry'])})")
    for key, label in label_map.items():
        for r in themes[key]:
            print(f"  [{label}] {r}")


if __name__ == "__main__":
    main()
