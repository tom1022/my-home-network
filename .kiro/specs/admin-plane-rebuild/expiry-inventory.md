# 到達手段の期限の棚卸し

本 spec (`admin-plane-rebuild`) が新設する到達手段が持つ期限を列挙し、恒久化したものと、期限切れの前に更新するために監視で捕捉する必要があるものに分類する (要件 4.7、タスク 2.3)。

`manual-operations.md` は運用者本人が手を動かす作業の記録であり、本ファイルの内容 (設計上の期限の分類) はそれに該当しないため、別ファイルとして分離した。

## 一覧

| # | 要素 | 期限の実体 | 分類 | 根拠 |
|---|------|-----------|------|------|
| 1 | tailnet のノード鍵 (`console-pi`) | タグを付与しない auth key で参加させた場合、node key に既定の有効期限が付く | **恒久化** | タグ付き auth key で参加させたことにより node key expiry が既定で無効化される。実機の `tailscale status --json` の `Self` に `KeyExpiry` が現れないことを確認済み (`manual-operations.md` の「tailnet 参加」節)。**後からタグを外す・張り替えると期限が復活する。**タグ設定を変更しないことが恒久化の前提条件であり、design.md もこれを明記している |
| 2 | cloudflared トンネルの token | Cloudflare の remotely-managed tunnel token に、公式ドキュメント上の自動失効の定めは無い。ローテーションはセキュリティ上のベストプラクティスとして案内されているのみで、期限切れによる失効ではない ([Tunnel tokens](https://developers.cloudflare.com/tunnel/advanced/tunnel-tokens)) | **恒久化** (自動失効なし) | 発行時に有効期限を設定しない。侵害が疑われた場合のローテーションは運用者判断に委ね、期限切れに備えた監視は不要 |
| 3 | 認証セッション (経路 1: Cloudflare Access 経由の Kanidm ログイン) | Access のセッション (既定 24h、最大 1 か月) が切れても、Kanidm 側のグローバルセッション (`authsession_expiry`、`terraform-kanidm/identities.tf` で 8h/28800 秒 または 24h/86400 秒) が有効な間は利用者の再ログインなしで新しい application token が自動発行される ([Session management](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/)) | **恒久化** (自己更新) | 利用者の再ログインで自動的に更新される既存の識別提供者の仕組みであり、IaC 側の監視・更新作業を要しない |
| 4 | 外部公開ホスト名の証明書 | 経路 1: Cloudflare Edge の Universal SSL (自動更新、運用者操作不要)。経路 2: `tailscale serve --https` が用いる Tailscale 発行の Let's Encrypt 証明書 (自動更新)。オリジン証明書は存在しない (cloudflared は `console-pi` から Cloudflare への outbound 接続のみで完結し、Caddy との間はローカルの平文転送) | **監視で捕捉** | 発行元 (Cloudflare / Tailscale) 側で自動更新されるが、design.md のタスク 4.3 で `host_health` が「証明書の残存期間」を閾値検査の対象に含め、外部公開のホスト名を含める設計になっている。自動更新が何らかの理由で失敗した場合に備え、恒久化に委ねきらず監視で捕捉する方針とする |
| 5 | Caddy の基本認証資格情報 | bcrypt ハッシュ化された固定の資格情報。有効期限という概念自体が無い | **恒久化** (期限なし) | 期限切れによる失効が発生しないため監視対象ではない。ローテーション方針そのものは design.md に明記が無く、運用者の判断に委ねられた未決事項として残る (期限監視の対象外という結論には影響しない) |

## 結論

- 監視で捕捉する必要があるのは **外部公開のホスト名の証明書の残存期間** のみ。実装は `host_health` (タスク 4.3/4.4) に委ねる
- 残りの 4 要素はいずれも恒久化 (期限による失効が構造的に発生しない、または利用者の再ログインで自己更新される) であり、追加の監視機構を要しない
