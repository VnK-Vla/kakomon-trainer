# Codex で名前付き問題セットを作る

名前付き問題セットは、既存の過去問IDを1つの試験内でまとめ、所有者だけが繰り返し演習するための機能です。セットの作成はブラウザやOpenAI APIからは行わず、Codexが選定したIDを専用CLIで登録します。

新作問題を所有者専用で登録する場合は、後半の「新作の個人問題セット」を使います。個人問題は通常の分野別・年度別・一覧・ランダム演習には混ぜず、所有者の進行中の問題セット周回からだけ取得できます。

## 前提

- 新しい `server.py` でアプリを一度起動し、問題セット用テーブルを導入しておきます。
- 所有者は `users` テーブルに既に存在するユーザーを、表記まで正確に指定します。
- 1セットは1試験の既存問題だけで構成します。
- 同じ所有者・試験内でセット名は重複できません。
- セットには1〜5,000件の重複しない問題IDを指定できます。
- CLIはスキーマを作成しません。未導入の場合は安全に停止し、アプリの再起動を案内します。

## 1. Codexで問題を選定する

Codexには、対象ユーザー、試験、選定条件、希望するセット名を伝えます。選定中のDBアクセスは必ずSQLite URIの `mode=ro` を使い、`server.init_db()` や更新SQLを実行しません。

選定結果として使うのは次の3項目だけです。

- `title`: 画面に表示する名前。前後の空白を除いて1〜80文字
- `exam`: DBに保存されている試験名との完全一致
- `question_ids`: 既存問題の正の整数ID。順序はセット定義として保存されます

問題文、選択肢、解答、解説、ユーザー履歴をmanifestへ複写しないでください。

## 2. `/tmp` にmanifestを置く

Git管理外の一時ファイルとして、例えば `/tmp/question-set.json` を作ります。

```json
{
  "title": "MRI・CT 要確認セット",
  "exam": "放射線診断専門医認定試験",
  "question_ids": [123, 456, 789]
}
```

使用できるキーは `title`、`exam`、`question_ids` だけです。未知のキー、重複ID、存在しないID、別試験のIDはエラーになります。

## 3. dry-runで検証する

リポジトリ直下で次を実行します。`--user` はアプリ上の実在ユーザー名に置き換えます。

```sh
python3 tools/manage_question_sets.py create /tmp/question-set.json \
  --user "user@example.com" \
  --db /home/keita/kakomon-trainer/data/questions.db \
  --dry-run
```

dry-runはDB更新もバックアップ作成も行いません。出力された問題数、年度別件数、分野別件数、所有者、試験、セット名を確認します。問題文や解答は出力しません。

## 4. 実際に作成する

dry-runと同じ引数から `--dry-run` だけを外します。

```sh
python3 tools/manage_question_sets.py create /tmp/question-set.json \
  --user "user@example.com" \
  --db /home/keita/kakomon-trainer/data/questions.db
```

CLIは更新前にSQLiteのbackup APIで、次の形式のスナップショットを作ります。

```text
backups/before-question-set-YYYYMMDD-HHMMSS/questions.db
```

同じ秒に複数回実行した場合は、バックアップディレクトリ名に連番が付きます。バックアップの整合性確認後、セット定義と項目を単一トランザクションで登録します。途中で失敗した場合、セット登録は全体がロールバックされます。

## 5. APIと画面で確認する

1. アプリの現在ユーザーが `--user` と一致することを確認します。
2. 対象試験を開き、「演習」から「問題セット」を選びます。
3. セット名、問題数、未開始状態が表示されることを確認します。
4. 必要なら `GET /api/question-sets?exam=<試験名>` でも、現在ユーザーのセットだけが返ることを確認します。
5. 「ランダムに始める」で開始し、再読み込み後に「続きから」で未完了問題へ戻れることを確認します。

確認が終わったら `/tmp/question-set.json` を削除します。問題セットを作り直したい場合も、既存セットを自動上書きはしません。画面で不要なセットを明示的に削除してから、新しいmanifestで作成します。

## GitHubへ公開しないもの

次はコミット、PR、Issue、チャットへの貼り付けをしません。

- `data/questions.db` と作成されたバックアップ
- `/tmp` のmanifest
- 過去問PDF、抽出画像、問題文、選択肢、解答、解説
- ユーザー名とユーザー履歴を含む出力
- `static/media/`、`static/source-pdfs/`、`imports/`、`work/`、`logs/`

公開してよいのは、秘密情報や問題データを含まないCLI本体、テスト、一般化された説明文書です。

## 新作の個人問題セット

新作問題は、既存問題IDのmanifestとは別に、リポジトリ外の非公開manifestへ置きます。最上位は `title`、`exam`、`questions` のみ、各問題は `year`、`category`、`question`、`choices`、`answer`、`explanation` のみです。画像は登録しません。

最初に新しい `server.py` で一時コピーDBを初期化し、乾式実行します。

```sh
KAKOMON_DATA_DIR=/tmp/kakomon-private-preview python3 -c 'import server; server.init_db()'

python3 tools/manage_private_question_sets.py create \
  /private/path/private-question-set.json \
  --user "owner@example.com" \
  --db /tmp/kakomon-private-preview/questions.db \
  --dry-run
```

乾式実行は所有者・試験・同名セット・問題形式・選択肢・単一正答・件数内訳だけを検証し、問題文や所有者名を出力しません。実登録では同じコマンドから `--dry-run` を外します。更新前にバックアップを作り、問題、所有者対応、問題セットを単一トランザクションで登録します。

個人問題は次のすべてから除外されます。

- 通常の問題一覧と検索
- 分野別・年度別演習
- 全問題ランダム演習
- 通常の問題数・年度・分野集計
- 他ユーザーの直接問題取得、解答登録、メモ保存、エクスポート

問題セットを削除した際、その個人問題がほかの問題セットから参照されていなければ、問題本文と解答履歴も削除されます。周回履歴を残したい場合は、先にセットを削除しないでください。
