# Kakomon Trainer

資格試験の過去問を、Raspberry Pi 上のブラウザアプリとして演習するためのプロジェクトです。

最初に読む文書:

- [docs/project-context.md](docs/project-context.md): 全体像、配置、運用ルール
- [docs/pi-codex-handoff.md](docs/pi-codex-handoff.md): Pi 上で Codex が作業するための引き継ぎ
- [docs/full-migration-handoff.md](docs/full-migration-handoff.md): 完全移行時の公開/非公開の分け方
- [docs/remote-access-backup-handoff.md](docs/remote-access-backup-handoff.md): Tailscale と Google Drive の引き継ぎ
- [docs/google-drive-backup.md](docs/google-drive-backup.md): Google Drive バックアップ
- [kakomon-trainer.service.example](kakomon-trainer.service.example): systemd 設定の見本

## このリポジトリに置くもの

GitHub には、アプリのコードと説明書だけを置きます。

- `server.py`
- `static/app.js`
- `static/app.css`
- `static/index.html`
- `tools/`
- `scripts/`
- `docs/`
- `README.md`
- `kakomon-trainer.service.example`

## このリポジトリに置かないもの

次のものは、著作権、利用者履歴、秘密情報に関係するため GitHub には置きません。

- SSH 鍵
- `work/`
- `data/questions.db`
- ユーザー履歴やメモを含む DB
- 過去問 PDF
- PDF から抜き出した画像
- `static/media/`
- `static/source-pdfs/`
- `imports/`
- `*.tar.gz` などの転送用ファイル

本番データは Raspberry Pi、バックアップは Google Drive などの外部ストレージで管理します。

## 起動

ローカル確認:

```sh
python server.py --host 127.0.0.1 --port 8081
```

本番では Raspberry Pi 上で `127.0.0.1:8081` に待ち受け、Tailscale などから接続します。

データ保存先を変える場合:

```sh
KAKOMON_DATA_DIR=/home/keita/kakomon-trainer/data python server.py --host 127.0.0.1 --port 8081
```
