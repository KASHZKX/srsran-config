# Two independent UEs, one PDU session each, using a shared GNU Radio ZMQ cell.
# Both UE processes use ue1, with separate TUNs for the Open-RMF network interface names.
.DEFAULT_GOAL := cp

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
CONFIG_DIR ?= $(ROOT)
RUN_DIR ?= $(ROOT)
OCUDU_BUILD ?= $(abspath $(ROOT)../../ocudu/build)
SRSRAN_BUILD ?= $(abspath $(ROOT)../../thesis-srsRAN_4G/build)
SUDO ?= sudo

.PHONY: cp up du ue ue2 gnu capture-init

capture-init:
	@mkdir -p "$(RUN_DIR)/logs" "$(RUN_DIR)/pcaps"

cp: capture-init
	cd "$(RUN_DIR)" && $(SUDO) "$(OCUDU_BUILD)/apps/cu_cp/ocucp" -c "$(CONFIG_DIR)/cu_cp.yml"

up: capture-init
	cd "$(RUN_DIR)" && $(SUDO) "$(OCUDU_BUILD)/apps/cu_up/ocuup" -c "$(CONFIG_DIR)/cu_up.yml"

du: capture-init
	cd "$(RUN_DIR)" && $(SUDO) "$(OCUDU_BUILD)/apps/du/odu" -c "$(CONFIG_DIR)/du_zmq.yml"

ue: capture-init
	@$(SUDO) ip netns list | awk '{print $$1}' | grep -Fxq ue1 || $(SUDO) ip netns add ue1
	cd "$(RUN_DIR)" && $(SUDO) "$(SRSRAN_BUILD)/srsue/src/srsue" "$(CONFIG_DIR)/ue.conf"

ue2: capture-init
	@$(SUDO) ip netns list | awk '{print $$1}' | grep -Fxq ue1 || $(SUDO) ip netns add ue1
	cd "$(RUN_DIR)" && $(SUDO) "$(SRSRAN_BUILD)/srsue/src/srsue" "$(CONFIG_DIR)/ue2.conf"

gnu:
	@mkdir -p "$(RUN_DIR)/gnuradio"
	grcc -o "$(RUN_DIR)/gnuradio" -r "$(CONFIG_DIR)/multi_ue_scenario.grc"

# ==================================================
# A. Dual-UE registration and per-interface routing
# ==================================================
.PHONY: ue-route-all ue-ping ue2-ping
ue-route-all:
	@$(SUDO) bash "$(ROOT)../scripts/ue-session-route.sh" ue1 tun_srsue_pdu1 1
	@$(SUDO) bash "$(ROOT)../scripts/ue-session-route.sh" ue1 tun_srsue_pdu2 2

ue-ping:
	@$(SUDO) ip netns exec ue1 ping -I tun_srsue_pdu1 -c 4 8.8.8.8

ue2-ping:
	@$(SUDO) ip netns exec ue1 ping -I tun_srsue_pdu2 -c 4 192.168.56.112

# ==================================================
# B. Open-RMF networking is managed by rmf_ws/Makefile
# ==================================================
# Use make -C ~/rmf_ws up-ue / up-mec / camera-dn-up.
# Use net-down-ue / net-down-mec / camera-dn-down there for cleanup.
