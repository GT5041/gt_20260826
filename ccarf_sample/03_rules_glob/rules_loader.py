"""claude/rules/ 配下のルールファイルを、YAML フロントマターの paths フィールド
(グロブパターン)で対象ファイルに適用するかどうか判定するサンプル。

これは CCAR-F (Claude Certification Program: Architect Foundations) の
Task Statement 3.3「Apply path-specific rules for conditional convention
loading」に対応する。各ルールファイルは Markdown + フロントマターで構成する。

    ---
    description: ルールの説明
    paths:
      - "**/*.py"
    alwaysApply: false
    ---
    (ここにルール本文の Markdown)

判定ロジック:
  - alwaysApply: true のルールは、対象ファイルに関わらず常に適用される
  - それ以外は paths のいずれかのグロブパターンにマッチしたときだけ適用される
    (= 「編集中のファイルにマッチするときだけロードされる」ことで、無関係な
    コンテキストとトークン消費を減らせる、というのが試験ガイドの主張)

グロブは "**" (0階層以上のディレクトリにマッチ) をサポートする:
    "**/*.py"       -> トップレベルの app.py にも、src/a/b.py にもマッチ
    "src/api/**/*"  -> src/api/users.py にも、src/api/v1/users.py にもマッチ
Python 標準の fnmatch は "**" を特別扱いしないため、ここでは "**" を含む
グロブを正しく解釈する簡易的な glob -> 正規表現変換を自前で実装している。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

# "**/" -> 0階層以上のディレクトリ(末尾の / 込み)
# "/**" -> "/" 以降が0文字以上の任意の文字列
# "**"  -> 任意の文字列(/ を含む)
# "*"   -> "/" を含まない任意の文字列
# "?"   -> "/" を含まない任意の1文字
_GLOB_TOKEN_RE = re.compile(r"(\*\*/|/\*\*|\*\*|\*|\?)")


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    pattern = pattern.replace("\\", "/")
    regex = "".join(
        {
            "**/": "(?:.*/)?",
            "/**": "(?:/.*)?",
            "**": ".*",
            "*": "[^/]*",
            "?": "[^/]",
        }.get(tok, re.escape(tok))
        for tok in _GLOB_TOKEN_RE.split(pattern)
    )
    return re.compile(f"^{regex}$")


@dataclass
class Rule:
    path: Path
    description: str
    paths: list[str]
    always_apply: bool
    body: str

    def matches(self, target_path: str) -> bool:
        if self.always_apply:
            return True
        target = target_path.replace("\\", "/")
        return any(_glob_to_regex(pattern).match(target) for pattern in self.paths)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta, body = m.group(1), m.group(2)

    meta: dict = {}
    current_list_key: str | None = None
    for line in raw_meta.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list_key:
            meta[current_list_key].append(stripped[2:].strip().strip('"'))
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if value == "":
                meta[key] = []
                current_list_key = key
            else:
                current_list_key = None
                meta[key] = value.lower() == "true" if value.lower() in ("true", "false") else value.strip('"')
    return meta, body.strip()


def load_rules(rules_dir: Path) -> list[Rule]:
    rules = []
    for md_path in sorted(rules_dir.glob("*.md")):
        meta, body = _parse_frontmatter(md_path.read_text(encoding="utf-8"))
        rules.append(
            Rule(
                path=md_path,
                description=meta.get("description", ""),
                paths=meta.get("paths", []),
                always_apply=bool(meta.get("alwaysApply", False)),
                body=body,
            )
        )
    return rules


def rules_for_file(rules: list[Rule], target_path: str) -> list[Rule]:
    return [r for r in rules if r.matches(target_path)]


def main() -> None:
    rules_dir = Path(__file__).parent / "claude" / "rules"
    rules = load_rules(rules_dir)

    print(f"claude/rules/ から読み込んだルール: {len(rules)} 件")
    for r in rules:
        print(f"  - {r.path.name}: description={r.description!r} paths={r.paths} alwaysApply={r.always_apply}")
    print()

    # 試験ガイド Exercise 2 の例 (paths: ["src/api/**/*"], paths: ["**/*.test.*"]) を
    # 実際にマッチさせて確認できるよう、対象ファイルを選んでいる
    targets = sys.argv[1:] or [
        "src/app.py",
        "docs/README.md",
        "src/api/users.py",
        "src/api/v1/orders.py",
        "src/components/Button.test.tsx",
        "notes.txt",
    ]
    for target in targets:
        matched = rules_for_file(rules, target)
        names = [r.path.name for r in matched] or ["(適用ルールなし)"]
        print(f"{target}: {', '.join(names)}")


if __name__ == "__main__":
    main()
