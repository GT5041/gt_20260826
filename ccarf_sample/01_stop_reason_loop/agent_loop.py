"""stop_reason のループ(エージェントループ)を体験するサンプル。

CCAR-F (Claude Certification Program: Architect Foundations) の
Task Statement 1.1「Design and implement agentic loops for autonomous task
execution」に対応する。

Claude のような LLM API は「1回の呼び出しで会話が完結するとは限らない」。
レスポンスに含まれる ``stop_reason`` を見て、呼び出し側が次にすべきことを
判断し、必要なら再度 API を呼び出す ―― これが agentic loop の核心。

    stop_reason == "tool_use"      -> ツールを実行し、結果を会話に追加して
                                       もう一度 API を呼ぶ(ループ継続)
    stop_reason == "end_turn"      -> モデルが最終回答を返した(ループ終了)
    stop_reason == "max_tokens"    -> トークン上限で打ち切られた
    stop_reason == "stop_sequence" -> 指定した停止文字列に到達した

試験ガイドが明示するアンチパターン(避けるべき実装)にも注意:
  - 自然言語のテキストを解析してループ終了を判断すること(NG)
  - イテレーション回数の上限を「主たる」停止判断に使うこと(NG。あくまで
    無限ループ防止の安全弁であるべきで、正しい停止判断は必ず stop_reason)
  - アシスタントの text コンテンツの有無を完了判定に使うこと(NG)
このサンプルの run_agent_loop() は、あくまで stop_reason だけで継続/終了を
判断し、MAX_ITERATIONS は異常系のフェイルセーフとしてのみ使っている。

このスクリプトは以下の2モードで動く。

  1. デフォルト(オフラインモード)
     API キー無しで動く「フェイクの Claude クライアント」を使い、
     tool_use -> tool_use -> end_turn という3ターンのやり取りを
     決定的に再現する。

  2. --live モード
     ``pip install anthropic`` した上で環境変数 ANTHROPIC_API_KEY を
     設定していれば、実際の Anthropic API を叩いて同じループ処理が
     動くことを確認できる。

実行方法:
    python agent_loop.py            # オフラインモード
    python agent_loop.py --live     # 実際の API を使うモード(要APIキー)
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# stop_reason のループ本体(フェイク/実APIどちらのクライアントでも共通)
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 10  # 無限ループ防止のガード


def block_to_dict(block: Any) -> dict:
    """レスポンスの content ブロックを、次のリクエストに積める辞書に変換する。"""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    raise ValueError(f"unsupported block type: {block.type}")


def run_agent_loop(
    client: Any,
    model: str,
    messages: list[dict],
    tools: list[dict],
    tool_impls: dict[str, Callable[..., Any]],
) -> str | None:
    """stop_reason を見ながら、必要な回数だけ API 呼び出しを繰り返す。"""
    for iteration in range(1, MAX_ITERATIONS + 1):
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=messages,
            tools=tools,
        )
        print(f"--- iteration {iteration}: stop_reason={response.stop_reason!r} ---")

        # モデルの発話(text / tool_use)を会話履歴に積む
        messages.append({"role": "assistant", "content": [block_to_dict(b) for b in response.content]})

        if response.stop_reason == "tool_use":
            # tool_use のブロックをすべて実行し、結果を次のユーザーメッセージとして返す
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"  tool_use: {block.name}(**{block.input})")
                result = tool_impls[block.name](**block.input)
                print(f"  -> 実行結果: {result}")
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": str(result)}
                )
            messages.append({"role": "user", "content": tool_results})
            continue  # ★ ここが「stop_reason のループ」の継続ポイント

        if response.stop_reason == "end_turn":
            final_text = "".join(b.text for b in response.content if b.type == "text")
            print(f"  最終回答: {final_text}")
            return final_text

        if response.stop_reason == "max_tokens":
            print("  トークン上限で打ち切られました。続きを要求するか、諦めるかは呼び出し側の判断。")
            return None

        if response.stop_reason == "stop_sequence":
            print("  stop_sequence に到達したため終了します。")
            return None

        raise RuntimeError(f"未知の stop_reason: {response.stop_reason}")

    raise RuntimeError(f"{MAX_ITERATIONS} 回ループしても終了しませんでした(無限ループ防止で打ち切り)")


# ---------------------------------------------------------------------------
# オフラインモード用のフェイク Claude クライアント
# ---------------------------------------------------------------------------

class _FakeBlock:
    def __init__(self, type_: str, **kwargs: Any) -> None:
        self.type = type_
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeResponse:
    def __init__(self, stop_reason: str, content: list[_FakeBlock]) -> None:
        self.stop_reason = stop_reason
        self.content = content


class _FakeMessagesAPI:
    """呼び出すたびに、あらかじめ用意した台本(script)を順番に返す。"""

    def __init__(self, script: list[_FakeResponse]) -> None:
        self._script = script
        self._i = 0

    def create(self, **_kwargs: Any) -> _FakeResponse:
        if self._i >= len(self._script):
            raise RuntimeError("フェイク台本の想定回数を超えて呼び出されました")
        response = self._script[self._i]
        self._i += 1
        return response


class FakeAnthropicClient:
    def __init__(self, script: list[_FakeResponse]) -> None:
        self.messages = _FakeMessagesAPI(script)


def build_fake_client() -> FakeAnthropicClient:
    """「2+3 を計算し、その結果に10を足して」という問いに対し、
    add ツールを2回呼んでから end_turn で終わる3ターンの台本を用意する。
    """
    script = [
        _FakeResponse(
            "tool_use",
            [_FakeBlock("tool_use", id="call_1", name="add", input={"a": 2, "b": 3})],
        ),
        _FakeResponse(
            "tool_use",
            [_FakeBlock("tool_use", id="call_2", name="add", input={"a": 5, "b": 10})],
        ),
        _FakeResponse(
            "end_turn",
            [_FakeBlock("text", text="2 + 3 = 5、さらに + 10 = 15 です。")],
        ),
    ]
    return FakeAnthropicClient(script)


# ---------------------------------------------------------------------------
# 共通: ツール定義とツールの実装
# ---------------------------------------------------------------------------

ADD_TOOL = {
    "name": "add",
    "description": "2つの整数を足し算する",
    "input_schema": {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
    },
}

TOOL_IMPLS = {"add": lambda a, b: a + b}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="実際の Anthropic API を使う(要 pip install anthropic と ANTHROPIC_API_KEY)"
    )
    args = parser.parse_args()

    if args.live:
        try:
            import anthropic
        except ImportError as e:
            raise SystemExit("`pip install anthropic` を実行してください") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("環境変数 ANTHROPIC_API_KEY を設定してください")

        client = anthropic.Anthropic()
        model = "claude-sonnet-4-5"
        messages = [{"role": "user", "content": "2+3を計算し、その結果にさらに10を足してください。addツールを使ってください。"}]
    else:
        print("[オフラインモード] フェイククライアントで stop_reason のループを再現します\n")
        client = build_fake_client()
        model = "fake-model"
        messages = [{"role": "user", "content": "2+3を計算し、その結果にさらに10を足してください。"}]

    run_agent_loop(client, model, messages, [ADD_TOOL], TOOL_IMPLS)


if __name__ == "__main__":
    main()
