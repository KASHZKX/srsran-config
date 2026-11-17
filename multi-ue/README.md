# Open-RMF 雙 UE、每台一條 PDU Session

OCUDU 使用 release_26_04，UE 使用原生 release_25_10。
從本目錄依序在獨立終端執行，保持程序運行。

~~~bash
make cp
make up
make du
make gnu
make ue
make ue2
~~~

GNU Radio 用既有 multi_ue_scenario.grc 將兩個 UE 接到同一小區。

| 元件 | IMSI 尾碼 | S-NSSAI | DNN | namespace | TUN |
| --- | --- | --- | --- | --- | --- |
| UE1，eMBB Camera | 001 | 1:010203 | internet | ue1 | tun_srsue_pdu1 |
| UE2，URLLC RMF 控制 | 002 | 2:112233 | internet2 | ue1 | tun_srsue_pdu2 |

這是兩個 srsue 程序、兩個 IMSI，每台 UE 只建立自己的 PSI 1。
兩個程序共用網路 namespace，各自建立不同的 TUN。
TUN 尾碼沿用 Open-RMF 現有介面名稱，對應兩個 UE。

兩條連線建立後，執行下列指令驗證各介面。

~~~bash
make ue-route-all
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
