# 手動操作の記録

宣言 (IaC / GitOps) の外で行った操作を記録する。

## 関門 A0: 移行元 (VM 105) への一時の ssh 公開鍵の追加

### 前提の確認結果

Phase 1 の宣言が済んでいること。

- `kubectl --context default -n argocd get app nextcloud traefik-config mailbox` は 3 つとも Synced / Healthy。
- nextcloud namespace に migration-mariadb、nextcloud-db-1 (CloudNativePG)、nextcloud-redis が Running。Deployment `nextcloud` は replicas 0。PVC `nextcloud-pvc` (900Gi) と `nextcloud-db-1` が Bound。IngressRoute `nextcloud` と `nextcloud-deny-password-login`、CronJob `nextcloud-backup` (suspend) が存在する。

接続先が VM 105 であること (192.168.1.11 は VM 110 の記述と重複している)。

- `qm config 105` は name=nextcloud、net0 の MAC は `BC:24:11:3B:60:EF`。`qm agent 105 get-host-name` は `tochiweb.mydns.jp`、ゲスト内 ens18 の IP は 192.168.1.11。
- k3s-agent-z440 の `ip neigh show 192.168.1.11` は `lladdr bc:24:11:3b:60:ef` で、VM 105 の MAC と一致する。
- VM 105 内で `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` を読むと `SHA256:AjzgjSkvCC9K1KSFcOn2Fbfd+tqZT2J3D36rbl20UHk`。k3s-agent-z440 からの `ssh-keyscan -t ed25519 192.168.1.11` と一致する。
- ホスト鍵 (k3s-agent-z440 から keyscan した値):
  - ED25519 `SHA256:AjzgjSkvCC9K1KSFcOn2Fbfd+tqZT2J3D36rbl20UHk`
  - ECDSA `SHA256:MdVfB9fI4ufpOAhe5Rgi/PCZzGNFJwQrzWXO76jFGk0`
  - RSA `SHA256:cx9srE+d4Oyql0a6M3SGnSOaz/6oegkZlwVon9C2kks`

追加先 (root) で受け入れられること。

- `sshd -T`: `permitrootlogin without-password`、`pubkeyauthentication yes`、`authorizedkeysfile .ssh/authorized_keys`。
- `/media/hdd0` は `www-data:www-data 770`、`config.php` は `www-data:www-data 640`。読み取りには root か www-data が要る。
- `/root/.ssh` (0700) と空の `/root/.ssh/authorized_keys` (0600) が既に存在した。

### 実施内容

- 追加先: VM 105 の `/root/.ssh/authorized_keys` に 1 行。実行は hp-z440 から `qm guest exec 105` (guest agent 経由、ゲストの root ディスク上の書き込みのみ)。
- 鍵: 一時の ed25519 鍵 (comment `nextcloud-migration-a0`)。行の先頭に `from="192.168.1.152",no-agent-forwarding,no-port-forwarding,no-X11-forwarding` を付けて接続元を k3s-agent-z440 に限る。
- 秘密鍵は作業機の scratchpad で生成し、k3s-agent-z440 の `/root/.a0_key` (0600) に置いた。ホスト鍵を固定する known_hosts は `/root/.a0_known_hosts` (0600)。
- 確認: k3s-agent-z440 から `ssh -i /root/.a0_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/root/.a0_known_hosts -o PasswordAuthentication=no root@192.168.1.11 hostname` が `tochiweb.mydns.jp` を返した。
- 影響範囲: VM 105 では `authorized_keys` が 0 行から 1 行になっただけ。`/dev/sdb`、VM の設定、サービスには触れていない。ゲストの auth.log に接続の記録が残る。

### 元に戻す手順

1. hp-z440 から `qm guest exec 105 -- sed -i '/nextcloud-migration-a0/d' /root/.ssh/authorized_keys` を実行し、`grep -c nextcloud-migration-a0 /root/.ssh/authorized_keys` が 0 であることを確かめる。
2. k3s-agent-z440 の `/root/.a0_key` と `/root/.a0_known_hosts` を `shred -u` で消す。
3. 作業機の scratchpad の鍵ペアを `shred -u` で消す。
