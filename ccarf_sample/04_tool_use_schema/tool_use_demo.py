"""tool_use と JSON Schema を組み合わせるサンプル。

CCAR-F (Claude Certification Program: Architect Foundations) の
Domain 4「Prompt Engineering & Structured Output」, 特に
Task Statement 4.3「Enforce structured output using tool use and JSON
schemas」と Task Statement 4.4「Implement validation, retry, and feedback
loops for extraction quality」に対応する。

Claude にツールを渡すときは、JSON Schema でそのツールの入力形式
(input_schema)を定義する。Claude はレスポンスの stop_reason="tool_use"
の中で、その Schema に従った引数を組み立てて ToolUseBlock として返す。
tool_use + JSON Schema は「JSON構文エラーを排除する」最も信頼できる方法だが、
「意味的な誤り」(合計値が合わない等)までは防げない、という点が試験ガイドの
重要な出題ポイントになっている。

このサンプルでは:
  1. JSON Schema でツール create_support_ticket の入力形式を定義する
     (必須/任意フィールド、enum + "other"+detail の拡張可能な分類パターンを含む)
  2. Claude が返す tool_use.input を想定したデータを用意する
  3. jsonschema ライブラリで input を Schema に照らして検証する
  4. スキーマ違反のケースを用意し、ValidationError になることを確認する
  5. tool_choice の3モード(auto / any / forced)の違いを確認する
  6. 「スキーマは通るが意味的には誤っている」ケース(数量×単価≠合計)を示し、
     tool_use + JSON Schema だけでは意味的エラーを防げないことを確認する

実行方法:
    pip install -r ../requirements.txt
    python tool_use_demo.py            # オフライン(スキーマ検証のみ)
    python tool_use_demo.py --live     # 実際の Anthropic API で tool_use を発生させる(要APIキー)
"""
from __future__ import annotations

import argparse
import json
import os

from jsonschema import ValidationError, validate

# ---------------------------------------------------------------------------
# ① ツールの入力形式を JSON Schema で定義する
# ---------------------------------------------------------------------------

CREATE_TICKET_TOOL = {
    "name": "create_support_ticket",
    "description": "サポートチケットを作成する",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 100},
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            # enum + "other" + detail string パターン:
            # あらかじめ列挙しきれない分類を "other" + category_detail で拡張可能にする
            "category": {
                "type": "string",
                "enum": ["billing", "technical", "account", "other"],
            },
            "category_detail": {
                "type": ["string", "null"],
                "description": "category が 'other' のときの自由記述。それ以外は null。",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
            # 元ドキュメント/会話に情報が無い場合に無理に値を作らせないよう、必須にせず null 許容にする
            "assignee": {"type": ["string", "null"]},
        },
        "required": ["title", "priority", "category"],
        "additionalProperties": False,
    },
}


def validate_tool_input(tool_input: dict) -> None:
    validate(instance=tool_input, schema=CREATE_TICKET_TOOL["input_schema"])


def handle_tool_use(tool_name: str, tool_input: dict) -> dict:
    if tool_name != CREATE_TICKET_TOOL["name"]:
        raise ValueError(f"unknown tool: {tool_name}")
    validate_tool_input(tool_input)  # ★ Claude から渡された input を必ず検証してから使う
    return {
        "ticket_id": "TCK-0001",
        "title": tool_input["title"],
        "priority": tool_input["priority"],
        "category": tool_input["category"],
        "tags": tool_input.get("tags", []),
    }


# ---------------------------------------------------------------------------
# ② Claude が返す tool_use.input を想定したサンプルデータ
# ---------------------------------------------------------------------------

VALID_EXAMPLE = {
    "title": "ログイン画面でエラーが出る",
    "priority": "high",
    "category": "technical",
    "tags": ["bug", "login"],
    "assignee": None,
}

# category が既存カテゴリに収まらない場合の "other" + detail パターン
VALID_OTHER_CATEGORY_EXAMPLE = {
    "title": "契約プランの変更方法について問い合わせたい",
    "priority": "low",
    "category": "other",
    "category_detail": "plan_change_inquiry",
}

INVALID_EXAMPLES = [
    # priority が enum の値以外
    {"title": "テスト", "priority": "urgent", "category": "technical"},
    # 必須項目 title が欠けている
    {"priority": "low", "category": "billing"},
    # additionalProperties: false に反する余計なフィールド
    {"title": "テスト", "priority": "low", "category": "billing", "unexpected_field": 123},
]


def run_offline_demo() -> None:
    print("=== ① ツール定義 (JSON Schema) ===")
    print(json.dumps(CREATE_TICKET_TOOL, ensure_ascii=False, indent=2))

    print("\n=== ② 正常系: スキーマに適合する tool_use.input ===")
    result = handle_tool_use("create_support_ticket", VALID_EXAMPLE)
    print(f"input:  {VALID_EXAMPLE}")
    print(f"result: {result}")

    print("\n=== ③ enum + 'other' + detail パターン(拡張可能な分類) ===")
    result = handle_tool_use("create_support_ticket", VALID_OTHER_CATEGORY_EXAMPLE)
    print(f"input:  {VALID_OTHER_CATEGORY_EXAMPLE}")
    print(f"result: {result}")

    print("\n=== ④ 異常系: スキーマ違反の tool_use.input ===")
    for bad_input in INVALID_EXAMPLES:
        try:
            handle_tool_use("create_support_ticket", bad_input)
            print(f"input: {bad_input} -> バリデーションを通過(想定外)")
        except ValidationError as e:
            print(f"input: {bad_input}")
            print(f"  -> ValidationError: {e.message}")

    print("\n=== ⑤ tool_choice の3モード ===")
    print_tool_choice_modes()

    print("\n=== ⑥ スキーマは通るが意味的には誤っているケース ===")
    demo_semantic_vs_syntax_error()


# ---------------------------------------------------------------------------
# ⑤ tool_choice: "auto" / "any" / 特定ツールの強制選択
# ---------------------------------------------------------------------------

def print_tool_choice_modes() -> None:
    modes = {
        "auto": {"type": "auto"},  # モデルはツールを呼んでもテキストで返してもよい
        "any": {"type": "any"},  # 必ず何らかのツールを呼ぶ(内容がテキストになるのを防ぐ)
        "forced": {"type": "tool", "name": "create_support_ticket"},  # 指定したツールを必ず呼ぶ
    }
    explanations = {
        "auto": "モデルが状況に応じてツール呼び出しかテキスト応答かを選択できる(デフォルト)",
        "any": "必ず何らかのツールを呼ばせたいとき(構造化出力を保証したいが、どのツールが適切かはモデルに任せる)",
        "forced": "特定のツールを最初に必ず呼ばせたいとき(例: enrichmentの前に extract_metadata を強制)",
    }
    for name, tool_choice in modes.items():
        print(f"- {name}: tool_choice={json.dumps(tool_choice)}")
        print(f"    -> {explanations[name]}")


# ---------------------------------------------------------------------------
# ⑥ JSON Schema は構文エラーは防げても、意味的エラーは防げないことを示すデモ
# ---------------------------------------------------------------------------

ORDER_LINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "quantity": {"type": "integer", "minimum": 1},
        "unit_price": {"type": "number", "minimum": 0},
        "total_price": {"type": "number", "minimum": 0},
    },
    "required": ["quantity", "unit_price", "total_price"],
    "additionalProperties": False,
}


def demo_semantic_vs_syntax_error() -> None:
    # quantity(3) * unit_price(100) = 300 のはずが、total_price は 500 になっている
    # -> 型・必須項目はすべて満たしているため JSON Schema のバリデーションは通ってしまう
    semantically_wrong_input = {"quantity": 3, "unit_price": 100, "total_price": 500}

    print(f"input: {semantically_wrong_input}")
    validate(instance=semantically_wrong_input, schema=ORDER_LINE_ITEM_SCHEMA)
    print("  -> JSON Schema バリデーション: OK(構文エラーは無い)")

    expected_total = semantically_wrong_input["quantity"] * semantically_wrong_input["unit_price"]
    actual_total = semantically_wrong_input["total_price"]
    if expected_total != actual_total:
        print(
            f"  -> しかし意味的には誤り: quantity*unit_price={expected_total} != "
            f"total_price={actual_total}"
        )
        print(
            "  -> 対策(Task 4.4): stated_total と calculated_total を両方抽出させ、"
            "食い違いがあれば conflict_detected=true を立てて人間のレビューに回す"
        )


# ---------------------------------------------------------------------------
# 実際の Anthropic API を使った tool_use デモ
# ---------------------------------------------------------------------------

def run_live_demo() -> None:
    try:
        import anthropic
    except ImportError as e:
        raise SystemExit("`pip install anthropic` を実行してください") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("環境変数 ANTHROPIC_API_KEY を設定してください")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        tools=[CREATE_TICKET_TOOL],
        tool_choice={"type": "any"},  # 必ず tool_use を返させる
        messages=[
            {
                "role": "user",
                "content": "ログイン画面でエラーが出る不具合について、優先度highのサポートチケットを作成してください。",
            }
        ],
    )
    print(f"stop_reason: {response.stop_reason}")
    for block in response.content:
        if block.type == "tool_use":
            print(f"tool_use: name={block.name} input={block.input}")
            validate_tool_input(block.input)  # 実際の API が返した input も同じ Schema で検証できる
            print("-> JSON Schema バリデーション OK")
            result = handle_tool_use(block.name, block.input)
            print(f"-> 実行結果: {result}")
        elif block.type == "text":
            print(f"text: {block.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="実際の Anthropic API で tool_use を発生させる")
    args = parser.parse_args()

    if args.live:
        run_live_demo()
    else:
        run_offline_demo()


if __name__ == "__main__":
    main()
