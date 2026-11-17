# Open-RMF 雙 UE、每台一條 PDU Session

OCUDU 使用 release_26_04，UE 使用原生 release_25_10。
先結束上一輪的兩個 UE、CU-CP、CU-UP、DU 與 GNU Radio。
從本目錄依序在獨立終端執行，保持程序運行。
make cp 預設先經 SSH 到 Core，依序重建 SMF、確認四個 UPF 的
PFCP 關聯，再重建 AMF，避免舊的 AMF Session context 觸發 SMF 崩潰。
SSH 帳號預設為 ubuntu@192.168.56.111，可用 CORE_SSH 覆寫。
本機尚未設定免密登入時，SSH 會要求 Core 帳號的密碼。

已自行重啟並確認 Core 時，可明確使用 make cp CORE_RESET=0。
make core-check 只檢查 Core，不會重啟。
make core-reset 只重啟 SMF、AMF，不修改 Core 程式碼或 Helm 設定。
這是避開既有 SMF 問題的啟動流程，並未修復 SMF 的空指標錯誤。
若有 srsue 程序仍在執行，重啟指令會停止並要求先關閉 UE。

~~~bash
make cp
make up
make du
make gnu
make ue
make ue2
~~~

GNU Radio 用既有 multi_ue_scenario.grc 將兩個 UE 接到同一小區。
重新註冊或任一 UE release 後，需完整結束並重啟六個元件，
讓 CU、DU、UE 與 GNU Radio 的 ZMQ 狀態一致。
兩台 UE 都要啟動，不要等第一台完成連線才啟動第二台。
一般重新開始仍用 make cp 的預設 Core 重啟流程。


| 元件 | IMSI 尾碼 | S-NSSAI | DNN | namespace | TUN |
| --- | --- | --- | --- | --- | --- |
| UE1，eMBB Camera | 001 | 1:010203 | internet | ue1 | tun_srsue_pdu1 |
| UE2，URLLC RMF 控制 | 002 | 2:112233 | internet2 | ue1 | tun_srsue_pdu2 |

這是兩個 srsue 程序、兩個 IMSI，每台 UE 只建立自己的 PSI 1。
兩個程序共用網路 namespace，各自建立不同的 TUN。
TUN 尾碼沿用 Open-RMF 現有介面名稱，對應兩個 UE。

make ue 與 make ue2 會以鎖避免同時建立 namespace 的競態，
並自動啟用 ue1 的 loopback。取得各自 TUN IPv4 後，自動設定
table 1001/1002 的 default route 與來源 IP 規則。
因此不需要手動執行 ip netns add 或 ue-route-all。
兩台 UE 共用 namespace，應依來源 IP 選擇 TUN，避免加入兩條
互相衝突的 main-table default route。未指定來源的應用不保證走哪條 UE，
應使用來源 IP 綁定或 Open-RMF 的網路配置。

若 90 秒仍未取得 PDU IPv4，啟動器會報錯並停止該 UE，
可用 UE_ROUTE_TIMEOUT 調整等待時間。
已有同名 TUN 時會拒絕啟動，以免使用上一個 UE 的介面。
結束 UE 時會保留共用 namespace 與其他應用的網路物件。
啟動器會將 Ctrl+C 傳給 srsue，並隨程序結束停止路由監測。

兩條連線建立後，執行下列指令驗證各介面。
ue-route-all 保留作為手動修復路由的指令，通常不需要另外執行。

~~~bash
make ue-ping
make ue2-ping
~~~

IP 以實際建立結果為準，預期池為 eMBB 10.60.0.0/17、
URLLC 10.60.128.0/17。CU-CP 的 AMF 端點是 192.168.56.111:31412，
CU-UP N3 是 User VM 的 192.168.56.113。

Open-RMF 依 ~/rmf_ws/src/rmf_demos/README.md 進行。
使用新的 SESSION，Server 上 Camera DN 為 192.168.56.115:5600，
MEC 為 192.168.56.112，User 的 Fleet Manager 與 relay 使用
172.31.252.1:22011/22012。make up-mec 的 PDU_IP 請填 UE2
的 tun_srsue_pdu2 IPv4。User 的 make up-ue 會呼叫
~/srsran-config/scripts/ue-session-route.sh，以此設定的 TUN 名稱取得 UE2 位址。

每次重啟 RAN 前，先用 Open-RMF 的 net-down-ue、
net-down-mec 與 camera-dn-down 撤回前次應用的網路設定。
一般註冊與 Open-RMF 的清理各由自己的 Makefile 管理。

## 本次 release 原因

2026-11-17 18:33:43 UTC，SMF 清理舊 Session 時，
SendPfcpSessionDeletionRequest 在 send.go:314 發生 nil pointer panic。
AMF 隨後紀錄 duplicated PDU session ID、SMF connection refused。
CU-CP 在 18:34:02–03 等待 20000 ms 仍未完成 PDU 建立後釋放兩台 UE。
當時 ue1 namespace 已存在，因此 namespace 缺失不是這次 release 原因。
來源路由是 PDU 成功後的資料面設定，無法解決上述 SMF 崩潰。

make ue-check 會顯示兩個 TUN 位址、來源規則、table 1001/1002，
並從兩個 UE 的來源 IP 各測試外網與 MEC。可用
make ue-check 2>&1 | tee /tmp/dual-ue-network-check.log 保存結果。
這個檢查不修改路由或重啟任何元件。

## 實機驗證

2026-11-17 18:52:58 UTC 的 ue-check 已確認兩台 UE 取得
10.60.0.1、10.60.128.1，各自使用 table 1001、1002 的來源路由。
每台 UE 分別 Ping 8.8.8.8 與 192.168.56.112，每組 3/3 成功，
共 12/12，零丟包。Core 新的 SMF、AMF 容器均無重啟。
本次驗證範圍為註冊、來源路由及基本連通性，不代表已完成
iperf 負載或 Open-RMF 應用驗證。
