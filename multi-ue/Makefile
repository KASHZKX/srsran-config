# Two independent UEs, one PDU session each, using a shared GNU Radio ZMQ cell.
# Both UE processes use ue1, with separate TUNs for the Open-RMF network interface names.
.DEFAULT_GOAL := cp

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
CONFIG_DIR ?= $(ROOT)
RUN_DIR ?= $(ROOT)
OCUDU_BUILD ?= $(abspath $(ROOT)../../ocudu/build)
SRSRAN_BUILD ?= $(abspath $(ROOT)../../thesis-srsRAN_4G/build)
SUDO ?= sudo
CORE_SSH ?= ubuntu@192.168.56.111
CORE_RESET ?= 1
UE_ROUTE_TIMEOUT ?= 90

.PHONY: cp up du ue ue2 gnu capture-init

capture-init:
	@mkdir -p "$(RUN_DIR)/logs" "$(RUN_DIR)/pcaps"

cp: core-prepare capture-init
	cd "$(RUN_DIR)" && $(SUDO) "$(OCUDU_BUILD)/apps/cu_cp/ocucp" -c "$(CONFIG_DIR)/cu_cp.yml"

up: capture-init
	cd "$(RUN_DIR)" && $(SUDO) "$(OCUDU_BUILD)/apps/cu_up/ocuup" -c "$(CONFIG_DIR)/cu_up.yml"

du: capture-init
	cd "$(RUN_DIR)" && $(SUDO) "$(OCUDU_BUILD)/apps/du/odu" -c "$(CONFIG_DIR)/du_zmq.yml"

ue: capture-init
	cd "$(RUN_DIR)" && $(SUDO) env UE_ROUTE_TIMEOUT="$(UE_ROUTE_TIMEOUT)" bash "$(ROOT)run-ue.sh" "$(SRSRAN_BUILD)/srsue/src/srsue" "$(CONFIG_DIR)/ue.conf" 1 "$(ROOT)../scripts/ue-session-route.sh"

ue2: capture-init
	cd "$(RUN_DIR)" && $(SUDO) env UE_ROUTE_TIMEOUT="$(UE_ROUTE_TIMEOUT)" bash "$(ROOT)run-ue.sh" "$(SRSRAN_BUILD)/srsue/src/srsue" "$(CONFIG_DIR)/ue2.conf" 2 "$(ROOT)../scripts/ue-session-route.sh"

gnu:
	@mkdir -p "$(RUN_DIR)/gnuradio"
	grcc -o "$(RUN_DIR)/gnuradio" -r "$(CONFIG_DIR)/multi_ue_scenario.grc"

# ==================================================
# A. Dual-UE registration and per-interface routing
# ==================================================
# make cp resets Core once, before CU-CP starts. Never reset Core in each UE target.
# SSH to Core must be available; its account must be allowed to run MicroK8s.
.PHONY: core-prepare core-check core-reset ue-route-all ue-ping ue2-ping ue-check
core-prepare:
	@if pgrep -x ocucp >/dev/null || pgrep -x srsue >/dev/null; then \
		echo "Stop the previous CU-CP and both UEs before make cp." >&2; exit 1; fi
	@if [ "$(CORE_RESET)" = 1 ]; then $(MAKE) --no-print-directory core-reset; \
	else echo "CORE_RESET=0: Core reset explicitly skipped."; fi

core-check:
	ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "$(CORE_SSH)" 'bash -s -- check' < "$(ROOT)core-session.sh"

core-reset:
	@if pgrep -x srsue >/dev/null; then \
		echo "Stop both UE processes before resetting Core." >&2; exit 1; fi
	ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "$(CORE_SSH)" 'bash -s -- reset' < "$(ROOT)core-session.sh"

ue-route-all:
	@$(SUDO) bash "$(ROOT)../scripts/ue-session-route.sh" ue1 tun_srsue_pdu1 1
	@$(SUDO) bash "$(ROOT)../scripts/ue-session-route.sh" ue1 tun_srsue_pdu2 2

ue-check:
	@$(SUDO) bash "$(ROOT)check-ue-network.sh"

ue-ping:
	@$(SUDO) bash "$(ROOT)ue-ping.sh" tun_srsue_pdu1 8.8.8.8

ue2-ping:
	@$(SUDO) bash "$(ROOT)ue-ping.sh" tun_srsue_pdu2 192.168.56.112

# ==================================================
# B. Open-RMF networking is managed by rmf_ws/Makefile
# ==================================================
# Use make -C ~/rmf_ws up-ue / up-mec / camera-dn-up.
# Use net-down-ue / net-down-mec / camera-dn-down there for cleanup.
