# 都立コート通知bot：Cloudflareへの定期起動移行手順（Cursor引き継ぎ用）

作成日：2026-10-10（日本時間）

## 1. 目的・作業範囲

対象は **`seirantomo1999-afk/-bot`**。荒川区botの `arakawa-bot` とは別リポジトリである。

GitHub Actionsの定期起動が約30分間隔にならない問題に対し、起動元だけをCloudflare WorkersのCron Triggersへ移す。Seleniumによる取得とGmail通知は、既存のGitHub Actionsで実行する。

**ユーザーの明示的な指定：木場公園のエラー対策は今回の対象外。** `selenium_check.py` のアラート処理・リトライ・取得条件・ブラウザ生成・対象公園を変更しない。Python全体のリファクタリングもこの移行に含めない。

この文書は実装・設定の手順書であり、移行完了を示すものではない。文書作成時点では、このリポジトリの移行コードを実装・デプロイしていない。Cloudflare上の都立bot用WorkerやGitHubのSecrets/Variablesの有無は、Cursor側で確認する。

移行後の流れ：CloudflareのCron → GitHubのworkflow_dispatch API → GitHub Actions → 既存の取得・通知。

## 2. 確認済みの現行コード

確認したmainのコミット：`ca3b9dc8f8d2d7d5d33955cda6e3ece437984596`。作業開始時には最新mainとの差分を再確認すること。

| ファイル／設定 | 現状 |
|---|---|
| `.github/workflows/notify.yml` | workflow名 `park_notifier`。`workflow_dispatch: {}` とschedule |
| 現行Cron | `0,30 22-23,0-15 * * *`（UTC）。日本時間07:00〜翌00:30に30分ごと |
| 並行実行 | `group: park_notifier`、`cancel-in-progress: true` |
| 実行環境 | ubuntu-latest、Python 3.11、Chrome、job timeout 10分 |
| 起動コマンド | `python gmail.py` |
| `gmail.py` | subprocessで `selenium_check.py` を実行。エラー通知を担当 |
| `selenium_check.py` | 空き取得と、空きを見つけた際の即時Gmail通知を担当 |
| 対象公園 | 東白鬚公園・汐入公園・木場公園・舎人公園・浮間公園 |
| Google認証 | GitHub Secretsの `GMAIL_CREDENTIALS_JSON`、`GMAIL_TOKEN_JSON` |

このbotは空き通知のみ。荒川区botの自動予約、Google Calendar参照、区の予約サイトへのログインは移植しない。

既存の注意点：`gmail.py` は取得が異常終了しても、エラーメール送信後に `sys.exit(0)` を返す。したがってActionsの緑色表示だけで取得成功とは判断できない。移行確認ではログの `returncode: 0` を確認する。この仕様の修正も今回は行わない。

## 3. Cursorが最初に行う確認

1. この文書がある `-bot` を開き、remoteが対象リポジトリであることを確認する。ローカルフォルダ名は別名でよい。
2. `git status --short` でユーザーの未コミット変更を確認する。既存変更を上書き・破棄しない。
3. 最新mainを取得し、移行用ブランチを作る。既に移行のブランチ・PR・Workerがあれば再利用し、重複作成を避ける。
4. Cloudflareの対象アカウントと、後述する都立用Workerの有無を確認する。
5. GitHubの既存Google Secretsがあることを名前で確認する。値をログやチャットに出さない。

新しく取得する場合のWindows PowerShell例：

```powershell
git clone https://github.com/seirantomo1999-afk/-bot.git metro-court-bot
cd metro-court-bot
git switch -c feat/cloudflare-scheduler
```

## 4. 追加・変更するファイル

| ファイル | 作業 |
|---|---|
| `.github/workflows/notify.yml` | 起動元inputと切替条件を追加。既存の取得・通知stepsを維持 |
| `cloudflare/worker.js` | Cronから、このリポジトリのworkflowを起動する |
| `cloudflare/worker.test.js` | 起動、権限エラー、並行実行、無効化をモックで検証 |
| `cloudflare/wrangler.jsonc` | 都立用Worker名、Cron、設定値 |
| `cloudflare/package.json` / `package-lock.json` | Wranglerとテスト・デプロイ用コマンド |
| `.gitignore` | `node_modules/`、`.wrangler/`、`.dev.vars*`、Google認証JSONなどを除外 |

**`gmail.py` と `selenium_check.py` は変更しない。** 既存依存パッケージや通知先も維持する。追加のGitHubテストworkflowは必要に応じて作成し、モックのテストだけを実行する。

荒川区側のschedulerを参考にできる：

- 参照PR：https://github.com/seirantomo1999-afk/arakawa-bot/pull/1
- 確認済みの参照コミット：`e91f557c0405400459c8566d731dd7c2d28c89ca`
- 参照ファイル：`cloudflare/worker.js`、`worker.test.js`、`package.json`、`package-lock.json`

この参照コードには権限診断、busy判定、無効化、POSTを自動リトライしない処理がある。取得・予約用Pythonコードや荒川区のworkflow全体はコピーしない。特に **`dry_run` inputと `BOOKING_ENABLED` を都立側に持ち込まない**。都立側は後述の `source` inputだけを受け取る。

## 5. GitHub workflowの変更仕様

### 5.1 起動元input

既存の `workflow_dispatch: {}` を次の形に変更する：

```yaml
on:
  workflow_dispatch:
    inputs:
      source:
        type: choice
        options: [manual, cloudflare]
        default: manual
        description: 起動元
  schedule:
    # UTC。日本時間07:00〜翌00:30。切替後はjob条件でスキップ
    - cron: "0,30 22-23,0-15 * * *"
```

GitHubのscheduleは復旧用として残す。CloudflareのCronも同じ時刻を使う。荒川区の7分・37分とは起動時刻が重ならない。

### 5.2 起動元の切替条件

GitHubのRepository Variable **`SCHEDULER_MODE`** を使う。未設定または `github` なら既存のschedule、`cloudflare` ならCloudflareのdispatchを処理する。手動起動はどちらでも許可する。

```yaml
permissions:
  contents: read

concurrency:
  group: park_notifier
  cancel-in-progress: false

jobs:
  run:
    if: >-
      (github.event_name == 'schedule' && vars.SCHEDULER_MODE != 'cloudflare') ||
      (github.event_name == 'workflow_dispatch' &&
       (inputs.source != 'cloudflare' || vars.SCHEDULER_MODE == 'cloudflare'))
    # 以下は既存のruns-on、timeout、stepsを維持
```

`cancel-in-progress: false` にして、新しい起動が取得・メール送信の途中の実行をキャンセルしないようにする。concurrencyのgroupはリポジトリ内で扱われる。

| 起動 | 未設定／github | cloudflare |
|---|---|---|
| GitHub schedule | 取得・通知を実行 | jobをスキップ |
| dispatch、source=cloudflare | jobをスキップ | 取得・通知を実行 |
| dispatch、source=manual | 取得・通知を実行 | 取得・通知を実行 |

workflow名 `park_notifier`、パス `.github/workflows/notify.yml`、実行コマンド `python gmail.py` は維持する。新しいinputを持つworkflowは、Workerを有効化する前にmainへ反映する。旧mainへ `source` を送ると入力の不一致で失敗する可能性がある。

## 6. Cloudflare Workerの実装仕様

### 6.1 設定ファイル

`cloudflare/wrangler.jsonc` の初期設定例：

```json
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "metro-court-bot-scheduler",
  "main": "worker.js",
  "compatibility_date": "2026-10-10",
  "workers_dev": false,
  "preview_urls": false,
  "observability": { "enabled": true },
  "triggers": { "crons": ["0,30 22-23,0-15 * * *"] },
  "vars": {
    "GITHUB_REPOSITORY": "seirantomo1999-afk/-bot",
    "GITHUB_WORKFLOW": "notify.yml",
    "GITHUB_REF": "main",
    "ENABLED": "false"
  }
}
```

荒川区の `arakawa-bot-scheduler` と別Workerにする。アカウントが複数ある場合は、`wrangler whoami` で確認した対象アカウントのIDを `account_id` に指定する。IDを推測しない。

### 6.2 起動APIと処理

- `ENABLED` が `true` でなければAPIを呼ばず、`disabled` として記録する。
- `GITHUB_TOKEN` Secretがなければ明示的に失敗する。
- 対象workflowのqueued/in_progress/waiting/pending/requestedの実行を確認し、残っていれば `busy` として見送る。
- 実行が残っていなければ次のAPIへPOSTする。

```text
POST https://api.github.com/repos/seirantomo1999-afk/-bot/actions/workflows/notify.yml/dispatches
```

送信するJSONは **これだけ**：

```json
{"ref":"main","inputs":{"source":"cloudflare"}}
```

- 認証ヘッダーにCloudflare Secretのトークンを使用する。トークンを本文・ログへ出さない。
- GitHub APIのバージョンは、参照実装と同じ検証済みの `2022-11-28` を利用できる。
- GET/POSTに通信タイムアウトを設ける。POSTのタイムアウトや失敗を自動リトライしない。起動済みの場合に二重通知を招くため。
- `scheduled` handlerの `ctx.waitUntil` で処理の完了を追跡する。エラーはログへ記録して再throwし、正常イベントとして隠さない。
- 成功ログの `accepted` はAPI受付を示すだけ。botの実行成功はGitHubログで判断する。
- 公開HTTP起動用の `fetch` handler、ドメイン、Cloudflare上のブラウザ実行は不要。

### 6.3 必要な認証を分ける

| 設定 | 用途・配置 |
|---|---|
| CloudflareへのWranglerログイン | Workerを作成・更新するPCで認証 |
| Cloudflare Secret `GITHUB_TOKEN` | 都立botのGitHub workflowを起動する専用トークン |
| GitHub Secret `GMAIL_CREDENTIALS_JSON` | 既存のGoogle OAuthクライアントJSON |
| GitHub Secret `GMAIL_TOKEN_JSON` | 既存のGmail送信トークンJSON |
| GitHub Variable `SCHEDULER_MODE` | このリポジトリの起動元切替 |

GitHubトークンはFine-grained PATで、Resource ownerを `seirantomo1999-afk`、対象を **`-bot` のみ**、Repository permissionsを **Actions: Read and write** にする。期限を設定し、更新時は都立WorkerのSecretを差し替える。荒川区のトークンが `arakawa-bot` のみに限定されている場合、都立botには使えない。

既存Google Secretsは再登録不要。都立bot用トークンをCloudflareに登録する際も、Google認証JSONをCloudflareへ移さない。

## 7. ローカル確認とmainへの反映

Cursorで実装を終えたら、まず外部通信をモックしたWorkerテストを実行する。少なくとも次を検証する：

- disabled時はAPIを呼ばない。
- Secret未設定で失敗する。
- `busy` 時はPOSTしない。
- 通常時はPOSTを1回だけ行い、本文が `source` だけの上記JSONと一致する。
- 権限不足・トークン失効・明示的なレート制限を判別して失敗する。
- POSTがタイムアウトしても再送しない。
- scheduledの失敗を隠さず、ログへトークンを出さない。
- workflowの条件が5.2の表と一致する。

PowerShell、Node.js 22以上の例：

```powershell
cd cloudflare
npm ci
npm test
npm run check
```

`package.json` に `test: node --test worker.test.js`、`check: wrangler deploy --dry-run`、`deploy: wrangler deploy` を用意する。`check` はビルド確認であり、本番デプロイではない。

差分を確認してPRを作成し、必要なチェックを通した変更をmainへ反映する。`SCHEDULER_MODE` はこの時点では `github` または未設定のままにして、既存scheduleを継続させる。

GitHub Actionsでmain、`source=manual` を指定して1回起動し、既存の取得と通知が動くことを確認する。**この手動実行は既存botと同様、空き通知・エラー通知メールを送る。** 自動予約は行わない。

木場公園などの既存取得エラーが再現した場合はログで報告するが、今回の移行で修正しない。起動経路の確認と取得結果の確認は分けて記録し、取得失敗を「移行して正常化した」と報告しない。

## 8. PCからデプロイ・Secret登録

同じPCのCursorターミナルで実行する：

```powershell
npx wrangler login
npx wrangler whoami
npm run deploy
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret list
```

- Cloudflareのログイン・本人認証・権限認可はユーザーが行う。
- 初回deployは `ENABLED=false`。Cronが来てもGitHubを起動しない。
- `secret put` の入力プロンプトに都立bot用GitHubトークンを入れる。ソースやコマンド引数に値を書かない。
- `secret list` では `GITHUB_TOKEN` の名前を確認する。有効性・GitHub権限は実際のAPIで確認する。
- 登録先が `metro-court-bot-scheduler` であることを確認する。

通常ログインで `localhost:8976` への戻りが失敗する場合は、同じPCで `npx wrangler login --device --browser=false` を使う。既存の `CLOUDFLARE_API_TOKEN` 環境変数があるとOAuthより優先されるため、`whoami` の認証元と対象アカウントを確認する。トークンを追加・上書きする前に、既存用途を確認する。

ChatGPT側では、端末の認証結果取得が接続制限で止まり、クラウドブラウザのGoogleログインも502になった。**その認証をPC側へ引き継げるとは考えず、PC上で認証する。** 既にPCのWranglerが正しいアカウントで認証済みならログインし直す必要はない。

## 9. 起動元の切替と稼働確認

1. Workerの `ENABLED` を `true` に変更してdeployする。GitHub側のmodeはまだ `github` とする。
2. 次のCronでWorkerが `accepted` を記録し、GitHubに `workflow_dispatch` が現れることを確認する。この段階ではjobがスキップされるのが期待動作。権限・inputのエラーがあれば先に直す。
3. GitHubの `-bot` のRepository Variableを **`SCHEDULER_MODE=cloudflare`** に変更する。
4. 次のCloudflare Cronで、GitHubの `Run notifier` が実際に実行されることを確認する。
5. 切替後の実行を少なくとも3回確認し、約30分ごとの起動要求と、その都度の実行結果を記録する。

GitHub設定画面：

- Variables：https://github.com/seirantomo1999-afk/-bot/settings/variables/actions
- Secrets：https://github.com/seirantomo1999-afk/-bot/settings/secrets/actions
- 実行履歴：https://github.com/seirantomo1999-afk/-bot/actions
- GitHub PAT作成：https://github.com/settings/personal-access-tokens/new

Cronの設定変更は反映まで最大15分程度かかる場合がある。Cloudflareが起動してもGitHubのrunner待ちやサイトの通信エラーは残る。正確な30分ごとの取得完了を保証する構成ではない。

Cloudflareへ移行後も、GitHubのschedule由来の実行履歴は現れる場合がある。jobがスキップされていれば正常で、Cloudflareからの取得実行は `event=workflow_dispatch` と `source=cloudflare` で確認する。

## 10. 切り分けと元に戻す方法

| 症状 | 確認 |
|---|---|
| `disabled` | Workerの `ENABLED` がfalseのまま |
| `GITHUB_TOKEN is not configured` | Secretの名前・対象Worker |
| 401 | GitHubトークンの失効・削除・入力ミス |
| 403 | `-bot` の選択、Actions権限、GitHub側ポリシー、レート制限 |
| 404 | リポジトリ／workflow名、対象リポジトリへのアクセス。不存在とは断定しない |
| 422 | mainのworkflow/input/ref。荒川区用 `dry_run` を誤送信していないか |
| `busy` が続く | GitHubのqueued/in_progress等。実行中のbotを無条件にキャンセルしない |
| `accepted` だが取得されない | jobのスキップ、`SCHEDULER_MODE`、input、GitHub実行ログ |
| 取得エラー | 既存スクレイパ側の結果。今回の移行では修正しない |

戻す場合は、まずGitHubの `SCHEDULER_MODE=github` にして既存scheduleを再開させる。その後Workerを `ENABLED=false` にしてdeployする。残っている実行を確認し、実行中の取得を強制終了しない。GitHub scheduleの以前の起動遅延は再発する可能性がある。

コード、Secret、切替Variableのどの段階で止まったかを明記する。テスト成功、ビルド成功、デプロイ成功、API受付成功、bot取得成功、30分間隔確認をそれぞれ区別して報告する。

## 11. 完了条件とCursorへの依頼文

完了条件：都立用Workerが正しいアカウントに存在し、SecretとCronが設定されている。CloudflareからGitHubへ約30分ごとに3回以上起動され、取得結果を確認できる。GitHub scheduleとの二重取得がなく、荒川区botの設定・トークン・コードに変更がない。

Cursorに渡す依頼文：

> このリポジトリの `docs/CLOUDFLARE_MIGRATION.md` を読み、都立コート通知botの起動元だけをCloudflareへ移行してください。木場公園のエラー対策とPythonの取得・通知ロジックの変更は対象外です。既存の作業・Secrets・Workerを確認し、未完了の実装、テスト、main反映、デプロイ、起動確認を進めてください。ログイン・本人認証・秘密情報の入力が必要な箇所だけユーザーへ引き継いでください。荒川区botは変更せず、移行完了と取得の成否を分けて報告してください。

## 12. 公式資料

- Cloudflare Cron Triggers：https://developers.cloudflare.com/workers/configuration/cron-triggers/
- Cloudflare Secrets：https://developers.cloudflare.com/workers/configuration/secrets/
- Wrangler認証：https://developers.cloudflare.com/workers/wrangler/commands/general/
- Workers権限：https://developers.cloudflare.com/workers/authorization/
- GitHub workflow_dispatch API：https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- GitHub workflowイベント：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- GitHub APIエラー：https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api
