#!/usr/bin/env python3
"""Claude Code の PreToolUse フックとして動作する「遮断」サンプル。

Claude Code はツールを実行する直前に、settings.json の
``hooks.PreToolUse`` に登録されたコマンドへツール呼び出しの情報を
JSON として標準入力(stdin)に渡して実行する。

このスクリプトは stdin から以下の形の JSON を受け取る想定:

    {
      "tool_name": "Bash",
      "tool_input": {"command": "rm -rf /"},
      ...
    }

危険なパターンにマッチした場合、標準出力に
``hookSpecificOutput.permissionDecision = "deny"`` を含む JSON を返す。
これを見た Claude Code はツールの実行を遮断し、
``permissionDecisionReason`` の内容を Claude 自身にも伝える。

何も出力せず終了コード 0 で終われば「許可(allow)」として扱われる。
"""
import json
import sys

# 遮断したいコマンドパターン(デモ用。実運用ではより網羅的な検査が必要)
DENY_PATTERNS = [
    "rm -rf /",
    "sudo ",
    ":(){:|:&};:",  # fork bomb
    "> /dev/sda",
    "chmod -R 777 /",
]

# 参照を遮断したい機密ファイルパス断片
DENY_FILE_FRAGMENTS = [
    ".env",
    "id_rsa",
    "credentials.json",
]


def deny(reason: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # 入力が読めない場合は安全側に倒して許可(何もしない)
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for pattern in DENY_PATTERNS:
            if pattern in command:
                deny(f"危険なコマンドパターンを検出したため遮断しました: '{pattern}'")

    if tool_name in ("Read", "Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        for fragment in DENY_FILE_FRAGMENTS:
            if fragment in file_path:
                deny(f"機密ファイルへのアクセスと判断し遮断しました: '{fragment}' を含むパス")

    # マッチしなければ何も出力せず正常終了 -> 許可
    sys.exit(0)


if __name__ == "__main__":
    main()
