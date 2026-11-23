# 非公開PRを能力値に反映するための設定

公開プロフィールの画像生成・毎時の定期更新は `.github/workflows/profile.yml` で動きます。
非公開の取得元を読む権限は、通常のプロフィールrepoの `GITHUB_TOKEN` にはありません。
次の読み取り専用トークンを設定すると、次回同期からPRが集計されます。

## 1. 読み取り専用トークンを作る

GitHubの Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token。

- Token name：`pixel-profile-read`
- Resource owner：`mitsuki-nyann`
- Repository access：Only select repositories → **集計したい取得元だけ**
- Repository permissions：**Pull requests: Read-only**
- Metadata: Read-only は自動付与されます。
- 有効期限は自分の運用に合わせて設定してください。期限後は更新が必要です。

書き込み権限、全repoへのアクセス、コードの変更権限は不要です。

## 2. プロフィールrepoに保存する

`mitsuki-nyann/mitsuki-nyann` の Settings → Secrets and variables → Actions → New repository secret。

- Name：`PROFILE_READ_TOKEN`
- Secret：作成したトークン

トークンはチャットやREADMEに貼らず、このSecret欄に保存してください。

同じ画面でもう1つ、`PROFILE_SOURCE_REPOS` というSecretを作り、集計する非公開repoを `所有者名/リポジトリ名` の形式で保存します。複数の場合はカンマ区切りです。実際の取得元名は公開設定ファイルに書かないでください。

## 3. 同期する

Actions → Update pixel profile → Run workflow。タイトルは空欄のままで実行します。
以後は毎時17分に同期します。GitHubの混雑時は遅れる場合があります。

## 公開される情報

非公開PRについて保存・表示するのは、匿名ID、マージ日時、活動の種類、能力の配分と一般的な記録名（例：「実装のPRを完了」）です。
PRの実際のタイトル、本文、URL、ファイル名、コードは公開しません。集計中だけ変更ファイル名とタイトルを読みます。

`generated/sync-status.json` の `private_sync` が `awaiting_configuration` なら取得元の設定待ち、`awaiting_token` ならトークン待ち、`configured` なら設定されています。API接続エラーはActionsの失敗として報告されます。

## マージ直後にも更新したい場合

毎時の同期に加え、`integrations/profile-on-merge.yml` を取得元側へ配置し、`PROFILE_DISPATCH_TOKEN` を設定する方法があります。
こちらはプロフィールrepoだけのActions書き込み権限が必要です。読み取りトークンとは分けてください。詳細はGUIDE.mdにあります。
