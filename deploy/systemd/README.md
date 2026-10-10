# systemd 使用者服務

這些單元檔對應網頁、獨立分析 worker、Cloudflare Tunnel 與定期備份。**路徑與掛載點是目前主機的部署設定**；換伺服器時，先檢查單元內的 `WorkingDirectory`、`EnvironmentFile`、`ExecStart` 與 `ConditionPathIsMountPoint`。

單元檔可從此資料夾連到 `~/.config/systemd/user/`，然後執行 `systemctl --user daemon-reload`。已存在的服務請先核對原本連結指向與服務狀態，再更換；不需為了整理原始碼而重啟服務。

備份、容量及還原步驟見[維運說明](../../docs/operations-20261008.md)。`chordlab-backup.service` 讀取的 `.env` 含私人設定；不要加入 Git。
