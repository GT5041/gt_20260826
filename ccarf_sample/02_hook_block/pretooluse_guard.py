#!/usr/bin/env python3
"""Claude Code / Claude Agent SDK の PreToolUse フックとして動作する「遮断」サンプル。

CCAR-F (Claude Certification Program: Architect Foundations) の
Task Statement 1.5「Apply Agent SDK hooks for tool call interception and
data normalization」と Task Statement 1.4「Implement multi-step workflows
with enforcement and handoff patterns」に対応する。

Claude Code はツールを実行する直前に、settings.json の
``hooks.PreToolUse`` に登録されたコマンドへツール呼び出しの情報を
JSON として標準入力(stdin)に渡して実行する。

このスクリプトは stdin から以下の形の JSON を受け取る想定:

    {
      "tool_name": "Bash",
      "tool_input": {"command": "rm -rf /"},
      ...
    }

危険なパターン/ビジネスルール違反にマッチした場合、標準出力に
``hookSpecificOutput.permissionDecision = "deny"`` を含む JSON を返す。
これを見た Claude Code はツールの実行を遮断し、
``permissionDecisionReason`` の内容を Claude 自身にも伝える。

何も出力せず終了コード 0 で終われば「許可(allow)」として扱われる。

このデモには2種類の遮断ルールを用意している:
  1. 安全ガード: 危険な Bash コマンド / 機密ファイルへのアクセスを遮断
  2. ビジネスルール強制: 試験ガイドの例(「$500を超える返金操作を遮断し、
     人間へのエスカレーションへリダイレクトする」)を再現した
     process_refund ツールの閾値チェック。プロンプトの指示だけに頼らず、
     hook で「決定論的に」ルールを強制する点がポイント。
"""
import json
import sys

# 遮断したい Bash コマンドパターン(デモ用。実運用ではより網羅的な検査が必要)
DENY_COMMAND_PATTERNS = [
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

# ビジネスルール: この金額を超える返金は自動承認せず、人間にエスカレーションする
REFUND_THRESHOLD = 500


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
        for pattern in DENY_COMMAND_PATTERNS:
            if pattern in command:
                deny(f"危険なコマンドパターンを検出したため遮断しました: '{pattern}'")

    if tool_name in ("Read", "Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        for fragment in DENY_FILE_FRAGMENTS:
            if fragment in file_path:
                deny(f"機密ファイルへのアクセスと判断し遮断しました: '{fragment}' を含むパス")

    if tool_name == "process_refund":
        amount = tool_input.get("amount", 0)
        if amount > REFUND_THRESHOLD:
            deny(
                f"返金額 ${amount} が閾値 ${REFUND_THRESHOLD} を超えているため、"
                "自動実行を遮断し人間のエスカレーションへリダイレクトします。"
            )

    # マッチしなければ何も出力せず正常終了 -> 許可
    sys.exit(0)


if __name__ == "__main__":
    main()
