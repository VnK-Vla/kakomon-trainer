# 疾患知識チェックリストの安全な作成・保守

疾患知識チェックリストは、監査済みカリキュラムから抽出した疾患を所有者だけに表示し、`わかる`・`あやしい`・`わからない`で自己確認する機能です。疾患データと利用者の自己評価は非公開DBだけに保存し、GitHubには載せません。

## 今回の定義

- 対象試験は `放射線診断専門医認定試験` です。
- 添付カリキュラム835行を、疾患・腫瘍・先天奇形・外傷・病的状態790項目へ原子化しています。
- 2015〜2025年の904問で登録正答肢に出現した169項目は `base_included=false`、残る621項目は `true` です。
- 問題リンクは `correct` と `structured_target` だけを保存します。問題文・誤答肢だけの一致は保存しません。同一問題で両方なら `correct` を優先します。
- 項目は `base_included=true`、または所有者がリンク問題を一度でも自動採点で誤答した場合に表示対象になります。過去誤答は最初の `is_correct=0` を記録し、後の正解では消しません。
- 試験問題の誤答は項目を表示対象へ加える根拠であり、疾患の自己評価ではありません。自己評価行は画面操作時にだけ作成されます。

## 画面での確認

- 疾患確認画面は、カリキュラム順の主領域ごとに独立した分野ページとして表示します。「前の分野」「次の分野」または分野選択欄で切り替えます。
- 1分野が12件を超える場合は、分野内を12件ずつに分け、一覧の上下にページ送りを表示します。全項目はブラウザ内に保持するため、進捗集計・検索・TSV出力の対象範囲は変わりません。
- 状態、キーワード、誤答条件を変えると分野内の1ページ目へ戻ります。分野選択欄の件数は、現在の絞り込みを各分野へ適用した件数です。
- 評価後は同じ分野を維持し、直前に評価したカードを確認してから次の未確認項目へ進めます。

## 非公開manifest

manifestはリポジトリ外に置きます。今回のCLIは、監査済みの件数、試験名、添付SHA-256を厳格に確認します。

```json
{
  "title": "診断専門医カリキュラム 未正答疾患チェック",
  "exam": "放射線診断専門医認定試験",
  "source_sha256": "7eb8f540e36557a950dbbc9199efe956c4dcd99aa47221df39c4b6dc2f8e1d52",
  "extraction_criteria": "監査基準の説明",
  "items": [
    {
      "disease_name": "疾患名",
      "aliases": ["別名"],
      "concept_type": "disease",
      "primary_area": "中枢神経",
      "areas": ["中枢神経"],
      "curriculum_refs": [
        {
          "no": 100,
          "chapter": "画像診断学・IVR(各領域)",
          "major": "各論",
          "middle": "中枢神経",
          "small": "疾患名"
        }
      ],
      "base_included": true,
      "question_links": [
        {"question_id": 123, "match_type": "structured_target"}
      ]
    }
  ]
}
```

`items` は790件、うち `base_included=true` は621件、`false` は169件でなければ停止します。非表示169項目には最低1件の `correct` linkが必要で、採用621項目に `correct` linkがある場合も停止します。疾患名、別名、カリキュラムNo.、問題IDの重複や未知キーも受け付けません。

## 作成

最初に新しい `server.py` でアプリを一度起動し、疾患チェック用テーブルを導入します。所有者は `users` テーブルに保存された表記を正確に指定します。

```sh
python3 tools/manage_disease_checklists.py create \
  /private/path/diagnostic_disease_checklist_manifest.json \
  --user "owner@example.com" \
  --db /home/keita/kakomon-trainer/data/questions.db \
  --dry-run
```

dry-runはmanifest、所有者、試験、問題ID、件数内訳、過去誤答による追加表示件数を検証します。DB更新もバックアップ作成も行わず、標準出力に所有者名を表示しません。

確認後、同じコマンドから `--dry-run` だけを外します。CLIは更新前にSQLite backup APIで `backups/before-disease-checklist-*/questions.db` を作り、`PRAGMA quick_check` を通してから、チェックリスト・790項目・問題リンクを1トランザクションで登録します。同じ所有者・試験・タイトルの自動上書きはしません。

## △・×の解説準備

`export-review` は、画面で明示的に `あやしい` または `わからない` と評価され、かつ解説本文または出典が未登録の項目だけをTSVへ出します。試験問題を誤答しただけの未評価項目は出力しません。

```sh
python3 tools/manage_disease_checklists.py export-review \
  --checklist-id 1 \
  --user "owner@example.com" \
  --output /tmp/disease-review.tsv \
  --db /home/keita/kakomon-trainer/data/questions.db
```

TSVには疾患名、自己評価、主領域、カリキュラム位置、過去誤答参照、解説、出典を含みます。出力先がリポジトリ内なら停止します。

解説は改行・HTMLを含まない短いプレーンテキスト、出典は1件以上のHTTPS URLにしてください。複数URLは ` | ` で区切ります。編集後はまずdry-runします。

```sh
python3 tools/manage_disease_checklists.py import-notes /tmp/disease-review.tsv \
  --checklist-id 1 \
  --user "owner@example.com" \
  --db /home/keita/kakomon-trainer/data/questions.db \
  --dry-run
```

実更新時は事前バックアップを作り、TSV出力後に疾患名、自己評価、カリキュラム位置、過去誤答状態が変わっていないことを再確認してから、全行を1トランザクションで更新します。

## 問題リンクの追加同期

問題DBの監査範囲が増えた場合、同じmanifest形でリンクだけを追加できます。既存リンクや項目は削除・上書きしません。

```sh
python3 tools/manage_disease_checklists.py sync-links \
  /private/path/diagnostic_disease_checklist_manifest.json \
  --user "owner@example.com" \
  --db /home/keita/kakomon-trainer/data/questions.db \
  --dry-run
```

追加を実行する場合も事前バックアップ、再検証、単一トランザクションを使います。新規リンク先に過去の `is_correct=0` があれば、未設定項目だけを最初の誤答日時で追加表示対象にします。

## GitHubへ載せないもの

- manifestと監査TSV・JSON
- 疾患一覧、問題リンク、カリキュラム位置を含む成果物
- `data/questions.db` とバックアップ
- `export-review` で出したTSVと取り込む解説・出典
- 利用者名、自己評価、過去誤答情報

公開してよいのは、具体的な疾患データや利用者データを含まないCLI、テスト、一般化したこの手順書だけです。
