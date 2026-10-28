.PHONY: cp up du ue ue-init ue-ping ue-status ue-test capture-init
.DEFAULT_GOAL := cp

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SRSRAN_SRC ?= $(abspath $(ROOT)../srsRAN_4G)
SRSRAN_BUILD ?= $(SRSRAN_SRC)/build
OCUDU_SRC ?= $(abspath $(ROOT)../ocudu)
OCUDU_BUILD ?= $(OCUDU_SRC)/build
UE_BIN ?= $(SRSRAN_BUILD)/srsue/src/srsue
CP_BIN ?= $(OCUDU_BUILD)/apps/cu_cp/ocucp
UP_BIN ?= $(OCUDU_BUILD)/apps/cu_up/ocuup
DU_BIN ?= $(OCUDU_BUILD)/apps/du/odu
UE_CONFIG ?= $(ROOT)ue.conf

UE_NS ?= ue1
UE_PDU ?= 1
UE_TUN ?= tun_srsue_pdu$(UE_PDU)

capture-init:
	@mkdir -p "$(ROOT)logs" "$(ROOT)pcaps"

cp: capture-init
	cd "$(ROOT)" && sudo "$(CP_BIN)" -c "$(ROOT)cu_cp.yml"

up: capture-init
	cd "$(ROOT)" && sudo "$(UP_BIN)" -c "$(ROOT)cu_up.yml"

du: capture-init
	cd "$(ROOT)" && sudo "$(DU_BIN)" -c "$(ROOT)du_zmq.yml"

ue-init:
	@sudo ip netns list | awk '{print $$1}' | grep -Fxq -- "$(UE_NS)" || sudo ip netns add "$(UE_NS)"

ue-test:
	ctest --test-dir "$(SRSRAN_BUILD)" --output-on-failure --no-tests=error -R '^(nas_5g_test|nas_5g_nssai_test|gw_multi_session_test|rrc_nr_multi_session_test|srsue_help|srsue_version)$$'

ue: capture-init
	@test -x "$(UE_BIN)" || { echo "Build srsRAN_4G with CMake and make first, or set UE_BIN to the built srsue executable."; exit 1; }
	@$(MAKE) --no-print-directory ue-init
	cd "$(ROOT)" && sudo "$(UE_BIN)" "$(UE_CONFIG)"

ue-ping:
	sudo bash "$(ROOT)scripts/ue-session-ping.sh" "$(UE_NS)" "$(UE_TUN)" "$(UE_PDU)"

ue-status:
	sudo ip -n $(UE_NS) -4 -br addr show

