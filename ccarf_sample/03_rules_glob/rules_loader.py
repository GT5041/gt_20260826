"""claude/rules/ 配下のルールファイルを、glob パターンで対象ファイルに
適用するかどうか判定するサンプル。

各ルールファイルは Markdown + フロントマター(YAML風のヘッダ)で構成する。

    ---
    description: ルールの説明
    globs:
      - "**/*.py"
    alwaysApply: false
    ---
    (ここにルール本文の Markdown)

判定ロジック:
  - alwaysApply: true のルールは、対象ファイルに関わらず常に適用される
  - それ以外は globs のいずれかのパターンにマッチしたときだけ適用される
    - パターンに "/" が含まれる場合はファイルの相対パス全体に対して照合
    - "/" を含まないパターン(例: "*.py")はファイル名(basename)に対して照合
"""
from __future__ import annotations

import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass
class Rule:
    path: Path
    description: str
    globs: list[str]
    always_apply: bool
    body: str

    def matches(self, target_path: str) -> bool:
        if self.always_apply:
            return True
        target = target_path.replace("\\", "/")
        basename = target.rsplit("/", 1)[-1]
        for pattern in self.globs:
            if "/" in pattern:
                if fnmatch.fnmatch(target, pattern):
                    return True
            else:
                if fnmatch.fnmatch(basename, pattern):
                    return True
        return False


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
                globs=meta.get("globs", []),
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
        print(f"  - {r.path.name}: description={r.description!r} globs={r.globs} alwaysApply={r.always_apply}")
    print()

    targets = sys.argv[1:] or [
        "src/app.py",
        "docs/README.md",
        "src/components/Button.tsx",
        "src/style.css",
        "notes.txt",
    ]
    for target in targets:
        matched = rules_for_file(rules, target)
        names = [r.path.name for r in matched] or ["(適用ルールなし)"]
        print(f"{target}: {', '.join(names)}")


if __name__ == "__main__":
    main()
