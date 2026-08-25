"""tool_use と JSON Schema を組み合わせるサンプル。

Claude にツールを渡すときは、JSON Schema でそのツールの入力形式
(input_schema)を定義する。Claude はレスポンスの stop_reason="tool_use"
の中で、その Schema に従った引数を組み立てて ToolUseBlock として返す。

このサンプルでは:
  1. JSON Schema でツール create_support_ticket の入力形式を定義する
  2. Claude が返す tool_use.input を想定したデータを用意する
  3. jsonschema ライブラリで input を Schema に照らして検証する
  4. スキーマ違反のケースも用意し、ValidationError になることを確認する

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
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assignee": {"type": "string"},
        },
        "required": ["title", "priority"],
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
        "tags": tool_input.get("tags", []),
    }


# ---------------------------------------------------------------------------
# ② Claude が返す tool_use.input を想定したサンプルデータ
# ---------------------------------------------------------------------------

VALID_EXAMPLE = {
    "title": "ログイン画面でエラーが出る",
    "priority": "high",
    "tags": ["bug", "login"],
}

INVALID_EXAMPLES = [
    # priority が enum の値以外
    {"title": "テスト", "priority": "urgent"},
    # 必須項目 title が欠けている
    {"priority": "low"},
    # additionalProperties: false に反する余計なフィールド
    {"title": "テスト", "priority": "low", "unexpected_field": 123},
]


def run_offline_demo() -> None:
    print("=== ① ツール定義 (JSON Schema) ===")
    print(json.dumps(CREATE_TICKET_TOOL, ensure_ascii=False, indent=2))

    print("\n=== ② 正常系: スキーマに適合する tool_use.input ===")
    result = handle_tool_use("create_support_ticket", VALID_EXAMPLE)
    print(f"input:  {VALID_EXAMPLE}")
    print(f"result: {result}")

    print("\n=== ③ 異常系: スキーマ違反の tool_use.input ===")
    for bad_input in INVALID_EXAMPLES:
        try:
            handle_tool_use("create_support_ticket", bad_input)
            print(f"input: {bad_input} -> バリデーションを通過(想定外)")
        except ValidationError as e:
            print(f"input: {bad_input}")
            print(f"  -> ValidationError: {e.message}")


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
