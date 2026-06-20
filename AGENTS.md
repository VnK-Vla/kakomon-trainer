# AI エージェントへの必須指示

このファイルは、このリポジトリで作業するすべての AI エージェントが最初に読む案内です。

## 最初に必ず読むもの

作業を始める前に、必ず次の順番で確認してください。

1. `AGENTS.md`
2. `README.md`
3. 必要に応じて `docs/project-context.md`

移行、バックアップ、Raspberry Pi 上での作業、リモートアクセスに関係する変更を行う場合は、README の「最初に読む文書」に載っている関連ドキュメントも確認してください。

## 作業時の基本ルール

- このリポジトリは、資格試験の過去問演習アプリです。
- 著作権、利用者履歴、秘密情報に関係するファイルを GitHub に載せないでください。
- `data/questions.db`、過去問 PDF、抽出画像、ユーザー履歴、秘密鍵、バックアップアーカイブなどは慎重に扱ってください。
- 既存の変更を勝手に戻さないでください。
- 変更前に周辺の実装とドキュメントを読み、既存の方針に合わせてください。
- 動作確認できる変更では、可能な範囲で確認手順や結果を残してください。

## 重要な参照先

- `README.md`: プロジェクト概要と起動方法
- `docs/project-context.md`: 全体像、配置、運用ルール
- `docs/pi-codex-handoff.md`: Raspberry Pi 上で作業するための引き継ぎ
- `docs/full-migration-handoff.md`: 公開/非公開データの分離方針
- `docs/remote-access-backup-handoff.md`: リモートアクセスとバックアップ
- `docs/google-drive-backup.md`: Google Drive バックアップ
