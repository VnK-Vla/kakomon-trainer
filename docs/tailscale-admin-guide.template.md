# Tailscale管理者向け設定メモ

この文書は、Raspberry Pi上の過去問演習サイトをTailscale経由で限定公開するためのテンプレートです。
実際のURL、メールアドレス、IPアドレス、SSH鍵の場所は書き込まず、必要な場所だけ自分用の非公開メモに転記してください。

## GitHubに置かないもの

- 本番DB
- 問題画像
- ユーザー履歴
- ユーザーメモ
- 元PDF
- DBバックアップ
- 画像バックアップ
- SSH鍵
- 実際のTailscale URL
- 管理者や利用者のメールアドレス一覧

## Raspberry Pi側の基本方針

アプリ本体はRaspberry Pi内の `127.0.0.1:8081` で待ち受けます。
外部公開はTailscale Serveに任せます。

直接 `0.0.0.0:8081` で公開すると、Tailscaleのログイン情報を経由しないアクセスを受ける可能性があるため避けます。

## 管理者の指定

管理者は環境変数で指定します。

```text
KAKOMON_ADMIN_USERS=your-email@example.com
```

複数人を管理者にする場合はカンマ区切りにします。

```text
KAKOMON_ADMIN_USERS=your-email@example.com,second-admin@example.com
```

## Tailscale Serveの例

アプリがRaspberry Pi上で `127.0.0.1:8081` に起動している状態で、Tailscale Serveを有効にします。

```bash
sudo tailscale serve --bg 8081
```

表示されたURLを、利用者向け案内文書の `https://your-device.your-tailnet.ts.net` と置き換えてください。

## 利用者を招待する方法

少人数で使う場合は、Tailscaleの端末共有または同じTailnetへの招待を使います。
利用者に見せたくない他の機器がある場合は、TailscaleのAccess controlsでRaspberry Piだけを許可する設定にします。

## 動作確認

1. Tailscaleをオンにする
2. ブラウザでTailscale ServeのURLを開く
3. 左上に自分のTailscaleログイン名が表示されることを確認する
4. 管理者だけがユーザー管理画面や編集機能を使えることを確認する
5. 利用者アカウントでは問題編集やユーザー管理画面が見えないことを確認する

