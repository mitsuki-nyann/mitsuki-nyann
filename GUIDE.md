# PIXEL PROFILE / DS風・PR自動成長版

ダイヤモンド・パール頃のDS画面をイメージしたプロフィールです。上段はキャラクター・タイプ・能力値、下段は特性・資格・冒険の記録。添付画像を参考に作成した黒髪・眼鏡・メイド服のドット絵を組み込んでいます。

Python 3.10以上、追加ライブラリなし。画像生成はオフラインでも動きます。GitHub APIへの接続は `sync` のときだけです。GitHubに配置後はActionsが実行します。

## 新しく追加したこと

- ドット猫を `assets/maid.png` のメイドキャラクターに変更。
- マージされた本人のPRを1件1回集計。対象repoは設定で指定します。非公開の取得元はSecretsに保存します。
- PRの変更ファイルから、数学・電気・実装・設計・検証・共有へEXPを配分。
- **タイプは直近20件のPRでEXPが多い上位2分野**。同点なら最近伸びた分野を優先。
- **特性は直近20件で最も多い取り組みの種類**。同点なら最近の種類を優先。
- PRマージ直後に更新を依頼する連携設定と、毎時の補完同期を同梱。

PRを開いただけ、未マージ、単に閉じた場合は加算しません。プロフィール画像が変わるのは同期処理の完了後です。公開プロフィール用の設定を同梱しています。非公開PRの接続は `CONNECT_PRIVATE.md` を参照してください。

## 画面を見る

ZIPを展開してから `demo/preview.html` を開くと架空の活動による完成見本を表示します。`demo/preview.png` は静止画の見本です。

実際の記録は `generated/preview.html`。初期状態は **Lv.1 / 0 EXP / NORMAL**。見本は実績に加算しません。READMEには `generated/profile.svg` を貼ります。SVGにはキャラクター画像を埋め込んであり、外部画像サービスは不要です。

## GitHubプロフィールへ配置する

1. 公開リポジトリ `mitsuki-nyann/mitsuki-nyann` を用意します。ユーザー名と同じリポジトリ名がプロフィール表示の条件です。
2. ZIP内の `pixel-profile` フォルダーの**中身**をリポジトリ直下へ置きます。既存READMEがあれば置き換えず、`![ステータス](generated/profile.svg)` の行だけ加えても使えます。
3. `profile.json` の `github.actor`、`github.sources`、開始日 `github.since` を確認します。現在の開始日は2026年11月23日0時（日本時間）です。
4. `.github/workflows/profile.yml` も配置します。Androidのファイル選択で隠しフォルダーが見えなければ、GitHubの「Add file → Create new file」で同じパスを指定し内容を貼り付けてください。
5. Actions → Update pixel profile → Run workflow。タイトルは空欄にして初回同期を実行します。

以後は毎時17分に補完同期します。混雑などで遅れる場合があります。毎時は最大1日24回動くため、対象repoが大きい場合は頻度を下げてください。

### PRがマージされた直後に更新する

対象が別のrepoの場合、プロフィール側のworkflowだけではそちらのPRイベントを直接受信できません。そのため以下の通知設定を使います。

1. プロフィールrepoへの **Actions: Read and write** 権限を持つfine-grained personal access tokenをGitHub設定で作ります。対象repoをプロフィールrepoだけに限定します。トークンをコードやチャットに書く必要はありません。
2. PRを作るrepo（例：example-project）の Settings → Secrets and variables → Actions に `PROFILE_DISPATCH_TOKEN` という名前で登録します。
3. `integrations/profile-on-merge.yml` を対象repoの `.github/workflows/profile-on-merge.yml` として保存します。デフォルトブランチに入れてください。
4. ファイル内の `PROFILE_REPOSITORY` と `PROFILE_ACTOR` が自分の設定と合っていることを確認します。
5. 本人のPRをマージすると、プロフィールrepoの更新処理を起動します。

通知workflowは `pull_request_target: closed` を使いますが、PRのコードをチェックアウト・実行せず、タイトルや本文をコマンドに展開しません。プロフィール更新の依頼だけを送ります。対象repoが増えたら同じ設定を追加してください。通知がなくても毎時の補完同期で反映できます。

## どう自動判定するか

### 1. PRの配点

| 種類 | EXP |
|---|---:|
| feat：機能追加 | 30 |
| fix：不具合修正 | 15 |
| refactor：整理 | 20 |
| test：テスト | 15 |
| docs：解説 | 15 |
| study：学習 | 10 |
| release：作品公開（手動） | 50 |
| qualification：資格取得（手動） | 100 |

PRの `xp:fix` などのラベルを優先し、次に `fix: 不具合を修正` のようなタイトルを読みます。

どちらも指定しない場合も分類します。変更先がテストだけならtest、共有用文書だけならdocs、数学・電気の教材だけならstudy、それ以外はfeatとして扱います。`chore:`・`ci:`・`build:`・`revert:` は自動分類で加算しません。`xp:skip` ラベルは除外用です。`release` と `qualification` は手動で記録します。

### 2. 能力への配分

| ファイル名・パスの例 | 伸びる能力 | タイプ表示 |
|---|---|---|
| math、calculus、linear_algebra、`.tex` | 数学 | MATH |
| electric、denko、circuit、複線図、回路 | 電気 | ELECTRIC |
| 通常のプログラムなど | 実装 | CODE |
| architecture、design、adr、設計、要件 | 設計 | DESIGN |
| tests、test_、`.test.`、`.spec.` | 検証 | TEST |
| docs、README、`.md`、`.pdf` | 共有 | SHARE |

表の特徴を複数含む場合は、電気→数学→検証→設計→共有→実装の優先順です。例：`docs/math.tex` は数学です。

1ファイルを1票として、そのPRのEXPを分割します。例えば `feat` のPRで実装1ファイル・テスト1ファイルなら **実装15＋検証15＝合計30 EXP**。ファイルや行数を増やしても、PR全体の配点は増えません。端数は小数部分が大きい分野から割り振り、同点なら設定の能力順で決めます。

これはファイル名や指定した目印による分類です。コードの難しさ、実際の理解度、成果の質をAIが評価する仕組みではありません。

### 判定を直す・指定する

- `stat:electric` ラベル：電気に全配分。
- `stat:code` と `stat:test`：指定した2分野へ均等配分。
- `docs(math): 線形代数の解説`：数学へ15 EXP。
- `xp:fix`：配点をfixに指定。
- `xp:skip`：そのPRを除外。

能力の指定は `stat:` ラベル→タイトルの括弧内→ファイル判定の順に優先します。

一度集計したPRの分類は記録として保持します。後からラベルを変えただけでは過去の分類は変わりません。訂正は `data/github.json` を編集し再生成してください。該当PRの記録を削除して同期し直す方法でも再分類できます。

## タイプ・特性とレベル

能力値と全体EXPは全期間の累積です。100 EXPごとに1レベルで、0 EXPがLv.1。各バーはそのレベル内の進捗です。

タイプと特性は**直近20件のPR**だけを見ます。手動の学習記録や資格取得は累積能力値には加算しますが、PR傾向のタイプ判定には含めません。

例えば実装中心ならCODE、テストのPRが増えればTESTが上位に入り、過去の実装PRが直近20件の範囲外になるとタイプが交代します。1件ごとに再計算しますが、順位が変わらなければタイプ表示も変わりません。休んだだけでは累積EXPを減らしません。

| 最多のPR種類 | 自動で付く特性 |
|---|---|
| feat | ものづくり |
| fix | しゅうりじょうず |
| refactor | せいりせいとん |
| test | たしかめじょうず |
| docs | つたえじょうず |
| study | たんきゅうしん |

`profile.json` の `growth.recent_prs` で件数、`growth.type_names` でタイプ名を変更できます。`growth.automatic` をfalseにすると、以前の固定タイプ・特性に戻せます。

## 自分好みにいじる場所

| ファイル | 内容 |
|---|---|
| profile.json | 名前・技・画像パス・配点・対象repo・タイプの設定 |
| assets/maid.png | キャラクター画像。別の透明PNGに差し替え可能 |
| data/activities.json | 手動の学習・資格記録 |
| data/github.json | 自動取得したPR記録と能力配分の重み |
| generated/stats.json | 再生成する集計結果。分野ごとの配分、タイプ、特性も確認できる |
| scripts/profile.py | `score`＝集計、`classify_pr`＝分類、`identity`＝タイプと特性、`render`＝画面 |
| .github/workflows/profile.yml | 更新間隔・手動記録フォーム |
| integrations/profile-on-merge.yml | 対象repoに置くPRマージ通知 |

配点を変えると**過去の記録も新しい配点で再計算**します。設定変更・記録削除では値が下がる場合があります。資格欄は最大4件です。取得時は `moves` の `mastered` をtrueにし、`status` に取得年月などを書きます。資格の取得自体をGitHubから自動判定しません。

## スマホから勉強を記録

Actions → Update pixel profile → Run workflowで、titleに「複線図を1問練習した」、kindにstudy、statにelectricを指定します。記録・再生成・コミットまで実行します。同じ成果は1回だけ登録してください。

## ローカルで動かす

```bash
python3 scripts/profile.py build
python3 scripts/profile.py demo
python3 -m unittest discover -s tests -v
python3 scripts/profile.py sync
```

手動記録の例：

```bash
python3 scripts/profile.py add --id manual:2026-11-23-denko-01 --kind study --stat electric --title "複線図を1問練習した"
```

`sync` は公開APIで動きます。必要に応じて環境変数 `GITHUB_TOKEN` を使います。Actionsでは標準トークンを使用します。外部PR通知用のトークンとは用途が異なります。

## 重複・移行・動作範囲

- 同じPRはrepo名＋PR番号で一度だけ集計します。再実行では増えません。
- 同じ成果を手動で登録すると別件です。二重登録を避けてください。
- 本人作成・マージ済み・開始日以降のPRが対象です。非公開repoは `private_summary: true` と `PROFILE_READ_TOKEN` を指定した場合のみ、匿名化した結果を集計します。Bot、他人、プロフィール自身のrepoは除外します。
- 旧版はコミット方式でした。今回はPR方式です。旧コミット記録がすでにある場合、対象repoの旧記録を整理してから切り替えてください。両方式を同時に使うと同じ成果を重ねて数えるため、プログラムで拒否します。
- `github.sources` へrepoを追加できます。対象がない場合は空配列で使えます。
- 開始日や対象repoを変更しても、保存済みの記録は自動削除しません。
- APIの失敗時は部分取得した結果を保存しません。変更ファイルが3000件以上のPRは不完全な判定を避けるため同期を中断します。
- 既存記録のPRについて変更ファイルを再取得しませんが、PR一覧は開始日以降を走査します。大きいrepoではAPI回数制限と同期頻度を考慮してください。
- GitHubの権限やブランチ保護によって自動コミットが禁止されている場合は、ルールに沿った更新経路が必要です。長期間活動のない公開repoは定期実行が停止する場合があります。
- 見本画像は実績ではありません。GitHub上の本番実行は配置後に確認してください。

## 参考

- [プロフィールREADME](https://docs.github.com/en/account-and-profile/how-tos/profile-customization/managing-your-profile-readme)
- [PR API](https://docs.github.com/en/rest/pulls/pulls)
- [workflow_dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
- [pull_request_targetの扱い](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)

プログラムはMITライセンスです。画像については `assets/ABOUT.md` を参照してください。
