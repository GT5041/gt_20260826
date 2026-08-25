# gt_20260826

for test

## CCAR-F 試験対策サンプルプログラム

`ccarf_sample/` 配下に、以下4つの機能・動作を確認できる独立したサンプルプログラムを用意しています。
すべて Python 3.10+ で動作し、①③④は API キー無しでもオフラインで実行できます。

| # | 機能 | ディレクトリ |
|---|------|-------------|
| ① | stop_reason のループ(エージェントループ) | `ccarf_sample/01_stop_reason_loop/` |
| ② | フックによる遮断(PreToolUse hook) | `ccarf_sample/02_hook_block/` |
| ③ | `claude/rules/` のグロブによるルール適用判定 | `ccarf_sample/03_rules_glob/` |
| ④ | tool_use + JSON スキーマ | `ccarf_sample/04_tool_use_schema/` |

### セットアップ

```bash
cd ccarf_sample
python3 -m venv .venv && source .venv/bin/activate   # 任意
pip install -r requirements.txt
```

`requirements.txt` の `anthropic` は①④を `--live`(実際のAPI呼び出し)で試す場合のみ必要です。
`jsonschema` は④の検証で使うため必須です。

---

### ① stop_reason のループの確かめ方

対象: `ccarf_sample/01_stop_reason_loop/agent_loop.py`

LLM の応答には `stop_reason` というフィールドがあり、呼び出し側はこれを見て
「ツールを実行してもう一度呼ぶ」か「会話を終える」かを判断します。

```bash
python3 01_stop_reason_loop/agent_loop.py
```

**確認ポイント:**
- 出力に `--- iteration 1: stop_reason='tool_use' ---` → `--- iteration 2: stop_reason='tool_use' ---`
  → `--- iteration 3: stop_reason='end_turn' ---` の3回のループが表示されること。
  `stop_reason='tool_use'` の間はループが継続し、`add` ツールが2回実行されていることが
  `tool_use: add(**{...})` の行から確認できます。
- `stop_reason='end_turn'` になった時点でループが止まり、`最終回答:` が出力されて
  プログラムが終了することを確認してください。
- コード内 `run_agent_loop()` の `MAX_ITERATIONS = 10` が「無限ループ防止のガード」に
  なっている点も確認してください(stop_reason が永遠に `tool_use` を返すような
  異常系でも、10回で強制的に例外を投げて止まります)。
- `--live` オプション + `ANTHROPIC_API_KEY` 環境変数があれば、実際の Claude API でも
  同じロジックが動くことを確認できます:
  ```bash
  export ANTHROPIC_API_KEY=sk-...
  python3 01_stop_reason_loop/agent_loop.py --live
  ```

---

### ② フックによる遮断の確かめ方

対象: `ccarf_sample/02_hook_block/`

Claude Code はツール実行の直前に `PreToolUse` フックへツール呼び出し情報を JSON で渡し、
フック側が `permissionDecision: "deny"` を返すと実行を遮断できます。

**確認方法A: ローカルでフックのロジックだけを検証(Claude Code不要)**

```bash
python3 02_hook_block/test_hook_locally.py
```

- `ls -la` のような通常コマンドは `=> ALLOW` になること
- `rm -rf /` や `sudo ...` のような危険なコマンドは `=> DENY` になり、
  `permissionDecision: "deny"` を含む JSON が標準出力に出ること
- `.env` や `id_rsa` を含むパスへの `Read`/`Write` も `=> DENY` になること
- 最後に全ケースの期待値と実際の結果が一致し、終了コード 0 でプログラムが終わること
  (`echo $?` で確認可能)

**確認方法B: 実際に Claude Code のフックとして動かす**

1. `ccarf_sample/02_hook_block/settings.example.json` の内容を、このプロジェクトの
   `.claude/settings.json`(または `settings.local.json`)にコピーする。
2. `ccarf_sample` ディレクトリで Claude Code を起動し、たとえば
   「`rm -rf /tmp/test` を実行して」のように危険なコマンドを依頼する。
3. ツールが実行される前に遮断され、`pretooluse_guard.py` が返した
   `permissionDecisionReason` の内容が Claude の応答に反映されることを確認する。
4. 逆に `ls -la` のような安全なコマンドは通常通り実行されることを確認する
   (= フックが誤検知していないこと)。

---

### ③ `claude/rules/` のグロブの確かめ方

対象: `ccarf_sample/03_rules_glob/`

`claude/rules/*.md` に、フロントマターで `globs`(適用対象パターン)と
`alwaysApply`(常時適用フラグ)を指定したルールファイルを置いています。

```bash
python3 03_rules_glob/rules_loader.py
```

デフォルトでは以下5つのファイルパスに対して、どのルールが適用されるかを判定します。

| 対象ファイル | 期待される適用ルール |
|---|---|
| `src/app.py` | `always-security.md`, `python-style.md` |
| `docs/README.md` | `always-security.md`, `docs-style.md` |
| `src/components/Button.tsx` | `always-security.md`, `frontend-style.md` |
| `src/style.css` | `always-security.md`, `frontend-style.md` |
| `notes.txt` | `always-security.md` のみ(他のどの glob にもマッチしない) |

**確認ポイント:**
- `always-security.md` は `alwaysApply: true` のため、**すべての**対象ファイルで
  適用ルールに含まれること。
- `python-style.md`(`globs: ["**/*.py"]`)は `.py` ファイルのときだけ適用されること。
- `notes.txt` のようにどの glob にもマッチしないファイルでは、`always-security.md`
  以外のルールが1つも適用されないこと。
- 任意のファイルパスを渡して、狙い通りマッチ/非マッチになるかも試してください:
  ```bash
  python3 03_rules_glob/rules_loader.py src/foo.py src/foo.rb docs/spec.md
  ```
  (`.rb` は `python-style.md`/`docs-style.md`/`frontend-style.md` のどの glob にも
  一致しないため、`alwaysApply: true` の `always-security.md` のみが適用されることを確認)
- `rules_loader.py` の `Rule.matches()` で、`/` を含む glob はパス全体に、
  含まない glob はファイル名(basename)にマッチさせている実装も合わせて確認してください。

---

### ④ tool_use + JSON スキーマの確かめ方

対象: `ccarf_sample/04_tool_use_schema/tool_use_demo.py`

Claude にツールを渡す際は `input_schema` に JSON Schema を指定します。Claude は
その Schema に従った引数を組み立てて `tool_use` ブロックとして返すため、
受け取った側でも同じ Schema でバリデーションするのが安全です。

```bash
python3 04_tool_use_schema/tool_use_demo.py
```

**確認ポイント:**
- `=== ① ツール定義 (JSON Schema) ===` に、`create_support_ticket` ツールの
  `input_schema`(`type: object`、`required: [title, priority]`、
  `priority` は `enum` で3値に制限、`additionalProperties: false`)が
  そのまま JSON として表示されること。
- `=== ② 正常系 ===` では、スキーマに適合する `input`(`title`, `priority`, `tags` あり)
  が `handle_tool_use()` を通過し、`result` にチケット情報が生成されること。
- `=== ③ 異常系 ===` では、次の3パターンすべてで `ValidationError` が発生すること:
  1. `priority` が `enum` に無い値(`"urgent"`) → `'urgent' is not one of [...]`
  2. 必須項目 `title` が欠けている → `'title' is a required property`
  3. スキーマに無い余計なフィールドを含む(`additionalProperties: false` 違反)
     → `Additional properties are not allowed (...)`
- `--live` オプション + `ANTHROPIC_API_KEY` があれば、実際に Claude が
  自然文のリクエストから `tool_use.input` を組み立てる様子と、
  それが同じ JSON Schema でそのままバリデーションできることを確認できます:
  ```bash
  export ANTHROPIC_API_KEY=sk-...
  python3 04_tool_use_schema/tool_use_demo.py --live
  ```

---

### まとめて実行する

①③④はオフラインでまとめて実行できます(②は上記の方法Aでテストハーネスを実行してください)。

```bash
cd ccarf_sample
python3 01_stop_reason_loop/agent_loop.py
python3 02_hook_block/test_hook_locally.py
python3 03_rules_glob/rules_loader.py
python3 04_tool_use_schema/tool_use_demo.py
```
