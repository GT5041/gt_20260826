"""Claude Code を使わずに、PreToolUse フックの遮断ロジックを検証するテストハーネス。

pretooluse_guard.py に、実際に Claude Code から渡されるのと同じ形の
JSON をパイプで流し込み、"許可(allow)" か "遮断(deny)" かを表示する。
"""
import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).parent / "pretooluse_guard.py"

CASES: list[dict] = [
    {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
    {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
    {"tool_name": "Bash", "tool_input": {"command": "sudo apt-get install curl"}},
    {"tool_name": "Read", "tool_input": {"file_path": "src/app.py"}},
    {"tool_name": "Read", "tool_input": {"file_path": "/home/user/.env"}},
    {"tool_name": "Write", "tool_input": {"file_path": "~/.ssh/id_rsa"}},
]


def main() -> None:
    exit_code = 0
    for case in CASES:
        proc = subprocess.run(
            [sys.executable, str(GUARD)],
            input=json.dumps(case),
            capture_output=True,
            text=True,
            check=False,
        )
        decision = "DENY" if '"permissionDecision": "deny"' in proc.stdout else "ALLOW"
        print(f"input: {case}")
        if proc.stdout.strip():
            print(f"  stdout: {proc.stdout.strip()}")
        print(f"  => {decision}\n")

        # "rm -rf" や "sudo" や機密ファイルを含むケースは DENY、それ以外は ALLOW を期待
        should_deny = any(
            p in case["tool_input"].get("command", "") for p in ["rm -rf /", "sudo "]
        ) or any(
            f in case["tool_input"].get("file_path", "") for f in [".env", "id_rsa"]
        )
        if should_deny != (decision == "DENY"):
            print(f"  !! 期待と異なる結果です (期待: {'DENY' if should_deny else 'ALLOW'})")
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
