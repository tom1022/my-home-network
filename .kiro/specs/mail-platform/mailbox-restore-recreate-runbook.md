# メールボックスの復元と再作成 (障害対応手順)

本書はメール基盤の障害対応時に単体で参照する手順書である。想定する障害は 2 種類あり、対応方法が異なる。

- **メールボックスの喪失**: `mail_backup` が取得した書庫からの**復元**で対応する。書庫は取得時点の状態であり、取得後に届いたメールは復元できない。
- **署名鍵・認証基盤上のメール用定義の喪失**: 書庫の対象外であり、**再作成**で対応する。DKIM の鍵は新しい鍵を生成して差し替える (旧鍵と同一の値には戻せない)。Kanidm 側の一部の資格情報 (サービスアカウントの API トークン、利用者のアプリケーションパスワード) もサーバが生成する値であり、同様に再発行しかできない。

## 前提: 書庫の構成

- 取得元: `k3s-agent-minipc` (`192.168.1.151`) 上の local-path PV ディレクトリ (`/var/lib/rancher/k3s/storage/<pvc-uid>_mailbox_mailbox-data`)。PV の実ディレクトリ名は PVC 再作成のたびに UID 部分が変わるため、`ls /var/lib/rancher/k3s/storage/*_mailbox_mailbox-data` で都度特定する。
- 保存先: `pbs` (LXC 202、`192.168.1.202`) の `/mnt/zfs-pool-0/mail-backup/mailbox-<UTC timestamp>.tar.gz`。世代数上限は既定 14 (`ansible/roles/mail_backup/defaults/main.yml` の `mail_backup_retain_generations`)。
- 取得は systemd timer (`mail-backup-pull.timer`、`OnCalendar=*-*-* 04:10:00` + 10 分のランダム遅延) による自動 pull。手動起動 (`systemctl start mail-backup-pull.service`) してもタイマーのスケジュール (次回発火日、および直近の発火実績) には影響しない。
- アーカイブは PV ディレクトリそのものを tar 化したもの。トップレベルのエントリ名が PVC ディレクトリ名 (例: `pvc-54c8818c-....－mailbox_mailbox-data/`) で、その下に利用者ごとの maildir (`<アカウント名>/mail/...`) が続く。
- 書庫の取得に使う SSH 鍵 (Infisical `MAIL_BACKUP_SSH_PRIVATE_KEY` / `MAIL_BACKUP_SSH_PUBLIC_KEY`) は forced command 付きで tar 抽出専用であり、**復元には使わない**。復元は運用者自身の通常の管理アクセス (ansible の接続鍵、`sudo`) で行う。

## 1. メールボックスの復元

復元は「特定の利用者 1 名分だけを復元する」場合と「PV 全体を復元する」場合とで手順が分岐する。通常の障害 (誤ってメールボックスを消した、特定利用者のデータを壊した) は前者で足りる。ノード全損など PV そのものを失った場合のみ後者を行う。

### 1.1 共通の準備

1. どの世代を復元に使うか決める。`pbs` 上で世代の一覧と内容を確認する。

   ```
   ansible pbs -m shell -a "ls -la /mnt/zfs-pool-0/mail-backup/" -b
   ```

2. 復元対象が含まれる世代を選ぶ。疑わしい場合は `tar tzf` で該当利用者のディレクトリが含まれることを事前に確認する。

   ```
   ansible pbs -m shell -a "tar tzf /mnt/zfs-pool-0/mail-backup/mailbox-<timestamp>.tar.gz | grep <アカウント名>" -b
   ```

### 1.2 利用者 1 名分の復元

1. `pbs` 上で、選んだ世代から対象利用者のサブツリーだけを取り出し、単独の tar に再パックする。

   ```
   ansible pbs -m shell -a "
     rm -rf /tmp/restore-verify && mkdir -p /tmp/restore-verify
     tar xzf /mnt/zfs-pool-0/mail-backup/mailbox-<timestamp>.tar.gz -C /tmp/restore-verify --wildcards '*/<アカウント名>/*'
     PVDIR=\$(find /tmp/restore-verify -maxdepth 1 -mindepth 1 -type d)
     tar czf /tmp/restore-verify/<アカウント名>-restore.tar.gz -C \"\${PVDIR}\" <アカウント名>
   " -b
   ```

   `--wildcards '*/<アカウント名>/*'` はディレクトリエントリそのもの (末尾がスラッシュのエントリ) にはマッチしない。`*/<アカウント名>` 単体のパターンを併用すると `Not found in archive` で失敗するため、配下のファイルにマッチするパターン 1 つだけを使う。

2. 復元先の PV ディレクトリ名を `k3s-agent-minipc` 上で特定する。

   ```
   ansible k3s-agent-minipc -m shell -a "echo /var/lib/rancher/k3s/storage/*_mailbox_mailbox-data" -b
   ```

3. **復元先に、事故で新規作成された空のメールボックスが既に存在しないか確認する。** IMAP ログインは、ホームディレクトリが存在しない利用者に対しても新しい `uidvalidity` で空の Maildir を自動的に作り直す (Dovecot の `userdb static` による既定動作)。復元前にこの自動生成物が残っていると、書庫に入っていた古い `uidvalidity` と衝突し、想定と異なる状態になる。復元前に対象ディレクトリを一度削除してから展開する。

   ```
   ansible pbs -m fetch -a "src=/tmp/restore-verify/<アカウント名>-restore.tar.gz dest=/tmp/<アカウント名>-restore.tar.gz flat=yes" -b
   ansible k3s-agent-minipc -m copy -a "src=/tmp/<アカウント名>-restore.tar.gz dest=/tmp/<アカウント名>-restore.tar.gz mode=0600" -b
   ansible k3s-agent-minipc -m shell -a "
     set -e
     PV=/var/lib/rancher/k3s/storage/<pvディレクトリ名>
     rm -rf \${PV}/<アカウント名>
     tar xzf /tmp/<アカウント名>-restore.tar.gz -C \${PV}
     chown -R 1000:1000 \${PV}/<アカウント名>
     find \${PV}/<アカウント名> -type d -exec chmod 2700 {} \;
     rm -f /tmp/<アカウント名>-restore.tar.gz
   " -b
   ```

   uid/gid は `1000:1000` (コンテナ内の `vmail`) 固定。ディレクトリの mode は `2700` (setgid、他ユーザーに一切開放しない) を明示し直す。`pbs` 側の中間ファイル (`/tmp/restore-verify/`) も後始末で削除する。

4. `dovecot` Pod を再起動する必要はない (次回ログイン時に新しいファイルがそのまま見える)。復元対象の利用者でログインし、`SELECT INBOX` / `SEARCH ALL` / `FETCH` でメールが取得できることを確認する。

### 1.3 PV 全体の復元 (ノード全損等)

1. `gitops-apps` の `apps/mailbox/pvc.yaml` の宣言どおりに `local-path` PVC を再作成させる (通常は ArgoCD の同期に任せる。PVC 自体は `Prune=false,Delete=false` の注釈により誤って削除されない設計だが、ノード全損でホスト側のディレクトリが失われた場合は PVC を再作成しない限り新しい空ディレクトリが払い出される)。
2. 新しい PV ディレクトリ名を特定した後、復元したい世代のアーカイブ全体を対象ディレクトリへ展開する。個々の利用者ごとに 1.2 の手順を繰り返すか、アーカイブ全体を一括で展開してから `chown -R 1000:1000` / ディレクトリの `chmod 2700` を一括適用する。
3. 展開後、少なくとも 1 名の利用者で IMAP ログインとメール取得を確認する。

### 1.4 復元成立の確認方法

「書庫から復元したメールボックスが取得できること」は、手順の記述だけでは確認したことにならない。以下のいずれかで実際に取得できることを確かめる。

- 対象利用者のアプリケーションパスワードで IMAPS (`mail.fickledev.com:993`) にログインし、`SELECT` / `SEARCH` / `FETCH` でメールの内容が復元前と一致することを確認する。
- 上記が使えない場合 (利用者本人が操作できない等) は `doveadm` 等で Maildir の内容を直接検査する。

本タスク (8.2) では、実際に書庫に取り込ませたテストメールを使ってこの手順どおりに復元を実施し、合格したことを確認済みである。手順・結果は `research.md` の「タスク8.2」節を参照。

## 2. 署名鍵・認証基盤上のメール用定義の再作成

書庫の対象外であり、失われた場合は以下の手順で**再作成**する (過去と同一の値には戻せない)。

### 2.1 DKIM 鍵の再作成

**順序が重要。公開鍵の DNS レコードを先に更新し、反映を確認してから秘密鍵を差し替える。** 逆の順序 (先に秘密鍵を差し替える) を取ると、新しい鍵で署名されたメールを DNS がまだ古い公開鍵しか返さない状態で受信側が検証し、DKIM 検証が失敗する。

1. 新しい鍵ペアを生成する。rspamd がコンテナに同梱されているため `rspamadm dkim_keygen` を使うと秘密鍵ファイルと DNS 用の TXT レコード値を一度に得られる (selector は既存と同じ `mail` に揃える)。

   ```
   rspamadm dkim_keygen -s mail -d fickledev.com -k mail.private > mail.dns.txt
   ```

2. `mail.dns.txt` の内容 (`v=DKIM1; k=rsa; p=...` 形式) を、DNS 側の TXT レコード (`mail._domainkey.fickledev.com`、`terraform/cloudflare_dns.tf` で管理) の値として反映し、`terraform apply` する。
   - 2026-09 時点で `terraform/cloudflare_dns.tf` には DKIM の TXT レコードはまだ存在しない (タスク 7.1 が MX/SPF/DKIM/DMARC の DNS レコード一式を新設する担当であり、本タスク完了後に着手する)。レコードが存在する場合はその値を更新し、存在しない場合はタスク 7.1 と同じ場所に新設する。
3. DNS の反映を外部から確認する (`dig TXT mail._domainkey.fickledev.com` が新しい公開鍵を返すこと)。TTL 分は必ず待つ。
4. 反映を確認した後、秘密鍵 (`mail.private` の内容) を Infisical の `MAIL_DKIM_PRIVATE_KEY` (prod) へ登録し、ローカルの一時ファイルは `shred` 等で確実に削除する。
5. VPS へ反映する。

   ```
   infisical run --env=prod -- ansible-playbook playbooks/mailserver.yml --limit vps
   ```

   （`ansible/roles/mailserver/tasks/main.yml` が `mailserver_dkim_private_key` を `/opt/mailserver/config/rspamd/dkim/fickledev.com-mail.private` へ配置し、rspamd がコンテナ起動時にこれを読み直す。）
6. 送信メールの `DKIM-Signature` ヘッダを実際に確認し、新しい鍵で署名されていること、および署名が 1 個 (旧来の OpenDKIM との二重署名になっていないこと) を確認する。

### 2.2 Kanidm 上のメール用定義の再作成

`terraform-kanidm/mail.tf` が宣言する 4 リソースのうち、**Terraform の宣言から再作成できる部分**と、**サーバが生成するため再作成のたびに値が変わる部分**を分けて扱う。

| リソース | 再作成方法 | 再作成後に変わるもの |
|---|---|---|
| `kanidm_group.mail_users` | `infisical run --env=prod -- terraform apply` (ワークスペース `kanidm-identity`) で再宣言どおりに作られる | **所属メンバーは Terraform の管理対象外** (設計上の意図的な選択)。グループ自体が失われて再作成した場合、既存の全メンバーシップも失われるため、実際にメール認証を使っている利用者を **API 経由で個別に再追加**する必要がある (`PUT /v1/group/mail_users/_attr/member`)。Terraform の宣言だけでは元の所属者一覧は復元できない |
| `kanidm_account_policy.mail_users` | 同上 (`terraform apply`) | なし (グループへ紐づく設定のみで、値そのものに秘匿情報はない) |
| `kanidm_application.mail` | 同上 (`terraform apply`) | **UUID が変わる。既存のアプリケーションパスワードは全て無効化される** (`ScimApplicationPasswordCreate` はアプリケーションの UUID に紐づく)。この 1 点が理由で、`mail` アプリケーション定義そのものが壊れていない限り `terraform taint` 等で意図的に再作成すべきではない |
| `kanidm_service_account.mail_ldap_search` | 同上 (`terraform apply`)。ただし `api_token` は `generate_api_token = true` 時にサーバが生成する computed 値であり、**任意の値を指定する経路がない**。既存のトークンを失った場合、`terraform taint kanidm_service_account.mail_ldap_search && terraform apply` のようにリソースの再作成を強制しない限り新しい値は発行されない | 2.3 を参照 |
| `kanidm_group_members.idm_mail_servers` | 同上 (`terraform apply`)。`mail_ldap_search` を再作成した場合はメンバー参照 (名前ベース) も自動的に追随する | なし |

### 2.3 サービスアカウントの LDAP 資格情報 (`mail-ldap-search`) の再発行

Kanidm のサービスアカウントの LDAP 資格情報は `dn=token` bind (サーバ生成の API トークン) であり、**再発行しかできない**。再発行後は以下の参照を更新する。

1. `terraform-kanidm` で `kanidm_service_account.mail_ldap_search` を再作成し (上記)、`terraform output -raw mail_ldap_search_api_token` で新しい値を取得する。
2. Infisical の `MAIL_LDAP_SEARCH_PASSWORD` (prod) を新しい値で上書きする。
3. **VPS 側を再適用する。** `mailserver_ldap_search_password` (`ansible/inventory/host_vars/vps/main.yml`、Infisical `MAIL_LDAP_SEARCH_PASSWORD` を参照) が docker-mailserver の `LDAP_BIND_PW` として compose 定義に埋め込まれるため、`infisical run --env=prod -- ansible-playbook playbooks/mailserver.yml --limit vps` を再適用してコンテナへ反映させる。
4. **格納側 (k3s / Dovecot) は更新不要。** `gitops-apps` の `apps/mailbox/` 一式を確認したが、`mail-ldap-search` のトークンを参照する箇所は存在しない。格納側の Dovecot は利用者自身のアプリケーションパスワードで bind するだけであり (`passdb ldap` の `bind_userdn` はテンプレートで組み立てる方式、検索を行わない)、このサービスアカウントの資格情報を検索用に使うのは VPS 側の docker-mailserver (Postfix の宛先照合 / Dovecot の宛先照合) のみである。したがって再発行後に更新が要る参照は VPS 側 (Infisical の値と、それを取り込む `mailserver.yml` の再適用) だけであり、格納側の manifest やシークレットに変更は不要。

### 2.4 アプリケーションパスワードの再発行

アプリケーションパスワードは**利用者自身の認証済みセッションでのみ発行できる**。管理者による代理発行は Kanidm の仕様上 `403 accessdenied` で拒否される (要件 2.13、本タスクの検証でも実測済み)。

- `kanidm_application.mail` を再作成した場合 (2.2 参照)、または利用者が単に自分のアプリケーションパスワードを紛失・失効させた場合は、**利用者本人へ再発行を案内する**必要がある。管理者が代わりに操作することはできない。
- 案内する内容は「利用者の設定手順」ドキュメント (要件 10、タスク 10.x で作成) の発行手順と同一 (`kanidm` CLI での対話ログイン → 特権昇格 → アプリケーションパスワードの発行)。発行は命令行の操作のみで行え、画面上の操作手段は存在しない。
- 発行されたパスワードは一度だけ表示され、再表示できない。紛失した場合も「再発行」であり「再表示」はできない。

## 3. 検証記録への参照

本書の手順 (1章) は、使い捨ての Kanidm 利用者を用いた実地検証で合格を確認済みである。検証の方法・使用したメッセージ・確認結果は `.kiro/specs/mail-platform/research.md` の「タスク8.2: 復元検証」節を参照。2章の再作成手順は記述のみであり、稼働中の DKIM 鍵・Kanidm のサービスアカウント・`mail_users` の既存メンバーに対しては実行していない。
