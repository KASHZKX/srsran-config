.PHONY: cp up du ue ue-init ue-test \
        ue-route ue-route-all ue-ping ue-status \
        capture-init

.DEFAULT_GOAL := cp

# ==================================================
# Paths
# ==================================================

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

SRSRAN_SRC ?= $(abspath $(ROOT)../thesis-srsRAN_4G)
SRSRAN_BUILD ?= $(SRSRAN_SRC)/build

OCUDU_SRC ?= $(abspath $(ROOT)../ocudu)
OCUDU_BUILD ?= $(OCUDU_SRC)/build

UE_BIN ?= $(SRSRAN_BUILD)/srsue/src/srsue
CP_BIN ?= $(OCUDU_BUILD)/apps/cu_cp/ocucp
UP_BIN ?= $(OCUDU_BUILD)/apps/cu_up/ocuup
DU_BIN ?= $(OCUDU_BUILD)/apps/du/odu

UE_CONFIG ?= $(ROOT)ue.conf

# ==================================================
# UE Network
# ==================================================

UE_NS ?= ue1
UE_PDU ?= 1
UE_TUN ?= tun_srsue_pdu$(UE_PDU)

# ==================================================
# Initialize
# ==================================================

capture-init:
	@mkdir -p "$(ROOT)logs" "$(ROOT)pcaps"

ue-init:
	@sudo ip netns list | awk '{print $$1}' | grep -Fxq -- "$(UE_NS)" || sudo ip netns add "$(UE_NS)"

# ==================================================
# OCUDU
# ==================================================

cp: capture-init
	cd "$(ROOT)" && sudo "$(CP_BIN)" -c "$(ROOT)cu_cp.yml"

up: capture-init
	cd "$(ROOT)" && sudo "$(UP_BIN)" -c "$(ROOT)cu_up.yml"

du: capture-init
	cd "$(ROOT)" && sudo "$(DU_BIN)" -c "$(ROOT)du_zmq.yml"

# ==================================================
# srsUE
# ==================================================

ue: capture-init
	@test -x "$(UE_BIN)" || { echo "Build thesis-srsRAN_4G first."; exit 1; }
	@$(MAKE) --no-print-directory ue-init
	cd "$(ROOT)" && sudo "$(UE_BIN)" "$(UE_CONFIG)"

ue-test:
	ctest --test-dir "$(SRSRAN_BUILD)" \
		--output-on-failure \
		--no-tests=error \
		-R '^(nas_5g_test|nas_5g_nssai_test|gw_multi_session_test|rrc_nr_multi_session_test|srsue_help|srsue_version)$$'

# ==================================================
# PDU Session Routing
# ==================================================

ue-route:
	@sudo bash "$(ROOT)scripts/ue-session-route.sh" \
		"$(UE_NS)" "$(UE_TUN)" "$(UE_PDU)"

ue-route-all:
	@$(MAKE) --no-print-directory ue-route UE_PDU=1
	@$(MAKE) --no-print-directory ue-route UE_PDU=2

# ==================================================
# PDU Session Testing
# ==================================================

ue-ping:
	@sudo bash "$(ROOT)scripts/ue-session-ping.sh" \
		"$(UE_NS)" "$(UE_TUN)" "$(UE_PDU)"

# ==================================================
# UE Status
# ==================================================

ue-status:
	@echo "=== UE Interfaces ==="
	@sudo ip -n "$(UE_NS)" -4 -br addr show
	@echo "=== Main Routing Table ==="
	@sudo ip -n "$(UE_NS)" -4 route show
	@echo "=== Policy Routing Rules ==="
	@sudo ip -n "$(UE_NS)" -4 rule show
	@echo "=== PDU Session 1 Routing Table ==="
	@sudo ip -n "$(UE_NS)" -4 route show table 1001
	@echo "=== PDU Session 2 Routing Table ==="
	@sudo ip -n "$(UE_NS)" -4 route show table 1002