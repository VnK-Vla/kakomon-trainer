# Claude向け：放射線診断模試作成の引き継ぎ

この文書は Kakomon Trainer の**放射線診断専門医認定試験**について、所有者専用の既存問題セットを安全に作成するための手順です。問題文、問題ID、解答、ユーザー名、解答履歴を会話・Git・manifest以外の場所へ出さないでください。

## まず守ること

- 対象試験は `放射線診断専門医認定試験` に固定する。他試験へ流用しない。
- 問題選定中のDBは SQLite URI の `mode=ro` と `PRAGMA query_only=ON` で開く。DDL、`server.init_db()`、直接の登録SQLは使わない。
- 登録は必ず `tools/manage_question_sets.py create` に委ねる。最初は必ず `--dry-run` を付け、利用者がその結果を見て明示承認するまで本番登録しない。
- 所有者は現在の Tailscale セッションの `/api/session` から取得し、`mode=tailscale` と既存 `users.name` の完全一致を確認する。名前を推測・列挙・会話へ出力しない。
- 既存の作業ツリー変更は利用者のものとして扱い、戻さない。サービス再起動も、問題セット周回の開始も行わない。

開始時には `AGENTS.md`、`README.md`、`docs/question-sets.md`、`tools/manage_question_sets.py` を読む。Codex環境では、補助スキル `/home/keita/.codex/skills/create-kakomon-diagnostic-mock/SKILL.md` も読む。

## 現在の利用者指定（第11回以降の「同様」）

これは標準の「直近2年平均・自己評価×50」ではなく、利用者が後から指定した履歴重点モードである。利用者が別条件を明示しない限り、次の規則を使う。

1. 100問、既存の公開過去問だけを選ぶ。`private_question_owners` に載る問題は除外する。
2. 分野比率と自己評価 `self_mark='wrong'` の50/50比率は固定しない。
3. 自動採点の `attempts.is_correct` を履歴条件に使う。`self_mark`、`warn`、最終自己評価で置き換えない。
4. 次の問題を除外する。
   - 3回以上解いて、すべて自動採点で正解。
   - 2回以上解いて、初回だけ自動採点で不正解、以後はすべて正解。
5. **直近4回の診断模試**（タイトルが `診断模試 第N回...` の所有者・同試験セット）に入った問題を厳密に除外する。次の回を作るときは、その時点の最新4回を取り直す。候補不足でも、この除外を黙って緩めない。
6. 優先順は次のとおり。
   1. `4回以上解答` かつ `自動採点で3回以上不正解` の問題を最大20問。直近5収録年度を優先し、不正解回数が多い、解答回数が多い、最終解答が古い順にする。
   2. `解答回数=1` の問題。直近5収録年度を優先し、最終解答が古い順にする。
   3. 上記で100問に達しないとき、`解答回数=2` かつ `1回目=正解、2回目=不正解` の問題。**2回目の解答日時が古い順**にする（この順序を年度優先より優先する）。
   4. なお不足するとき、`2回以上解答` かつ `不正解が2回以上` の問題を、不正解回数が多い、解答回数が多い、最終解答が古い順に補う。
7. 同順位だけ、固定seedのハッシュで決める。最終的な問題順もseedで決め、同じ履歴なら再現可能にする。

候補が100問に届かなければ停止し、どの候補群が何問不足したかだけを報告する。直近4回の再利用、上記除外の緩和、別の問題群への拡張は、利用者の新しい明示指示なしに行わない。

## 選定の実装メモ

`attempts` は各 `question_id` について `created_at, id` 昇順で並べる。以下の値を作る。

```text
answers       = is_correct の時系列
attempts      = len(answers)
wrong_count   = answers 内の 0 の数
last_at       = 最終解答日時
second_at     = 2回目の解答日時（2回解答条件だけで使用）
```

タイトルの回番号は、所有者・同試験の既存 `診断模試 第N回...` の最大値 + 1 にする。履歴重点モードでは、選定内訳が分かるよう、例えば次の形式を使う。

```text
診断模試 第N回（履歴重点・1回X・再誤答Y）
```

`X` は「1回のみ」選定数、`Y` は「1回目○・2回目×」選定数である。既存タイトルを上書き・改名しない。

## manifestとdry-run

manifestは毎回ユニークな `/tmp` 配下に0600で作成する。最上位キーは次の3個だけである。

```json
{
  "title": "診断模試 第N回（履歴重点・1回X・再誤答Y）",
  "exam": "放射線診断専門医認定試験",
  "question_ids": [1, 2, 3]
}
```

実際のIDを会話へ貼り付けない。重複なし・100件・公開問題のみであることを確認してから、次を実行する。

```sh
python3 tools/manage_question_sets.py create /tmp/UNIQUE-manifest.json \
  --user "CURRENT_TAILSCALE_OWNER" \
  --db data/questions.db \
  --dry-run
```

dry-run結果と選定結果で、タイトル、試験名、100問、年度別・分野別内訳が一致することを確認する。利用者には問題内容や個人情報を出さず、少なくとも次を提示して承認を待つ。

- タイトルと100問であること
- 直近4回との重複が0問であること
- 各優先群の採用数（1回のみ、1回目○・2回目×、繰り返し不正解）
- 直近5収録年度からの件数と旧年度補完数
- 分野別内訳（分野比率を固定していないこと）

`はい` 等の明示承認を得た後でも、登録直前に所有者、manifest、直近4回、解答履歴、タイトル未使用を読み直す。候補が変わっていたら本番登録せず、新しいdry-runと承認をやり直す。

## 承認後の登録と検証

登録前に、少なくとも `questions`、`attempts`、`users`、`question_sets`、`question_set_items`、`question_set_rounds` の件数、`PRAGMA quick_check`、`PRAGMA foreign_key_check` を記録する。次のコマンドだけで登録する。

```sh
python3 tools/manage_question_sets.py create /tmp/UNIQUE-manifest.json \
  --user "CURRENT_TAILSCALE_OWNER" \
  --db data/questions.db
```

CLIが作る `backups/before-question-set-YYYYMMDD-HHMMSS/questions.db` を残す。登録後は次を確認する。

- `questions`、`attempts`、`users` は不変。
- `question_sets` は +1、`question_set_items` は +100、`question_set_rounds` は不変。
- 対象セットは100問、ID重複なし、位置は0〜99、周回は未開始。
- 選定規則、直近4回との重複0、公開問題のみを再計算して確認。
- 本番DBとバックアップの `quick_check` は `ok`、`foreign_key_check` は空。
- 所有者の `GET /api/question-sets?exam=...` には表示され、別ユーザーには表示されない。`/healthz` も正常。

すべて成功してから一時manifestを削除する。失敗時はmanifestを残し、登録済みならバックアップ場所と検証済みの事実だけを報告する。DBの直接修復、サービス再起動、周回開始はしない。
