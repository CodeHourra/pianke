# 片刻 · Tauri 桌面客户端构建
#
# 用法:
#   make help          # 查看目标
#   make setup         # uv sync + npm 依赖 + 图标
#   make run           # 浏览器模式：uv run python app.py
#   make dev           # Tauri 桌面开发模式（自动 uv sync + 启动窗口）
#   make build-mac     # 构建 macOS .app（须在 macOS 上执行）
#   make build-windows # 构建 Windows 安装包（须在 Windows 上执行）
#   make build         # 按当前系统自动选择 mac / windows
#   make clean         # 清理 Rust 构建产物
#
# 环境变量:
#   PIANKE_MODES=all|fast,expert,...  安装 Python 依赖时启用的模式（默认 all）
#   PIANKE_NO_MIRROR=1                 禁用国内 PyPI / HF 镜像

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PIANKE_ROOT := $(ROOT)
DESKTOP := $(ROOT)/desktop
TAURI_DIR := $(DESKTOP)/src-tauri
TARGET_DIR := $(TAURI_DIR)/target/release/bundle
PIANKE_MODES ?= all

# 平台探测（macOS / Linux git 用 uname；Windows Git Bash / MSYS 用 OS）
UNAME_S := $(shell uname -s 2>/dev/null || echo Unknown)
ifeq ($(OS),Windows_NT)
  PLATFORM := windows
  PY_BIN := $(ROOT)/.venv/Scripts/python.exe
else
  ifeq ($(UNAME_S),Darwin)
    PLATFORM := mac
  else
    PLATFORM := other
  endif
  PY_BIN := $(ROOT)/.venv/bin/python
endif

NPM := npm
CARGO := cargo
UV := $(shell command -v uv 2>/dev/null || echo "$(HOME)/.local/bin/uv")
export UV
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

.DEFAULT_GOAL := help

.PHONY: help setup setup-python icons check build build-mac build-windows dev run clean artifacts \
        _npm-install _ensure-uv _check-toolchain _require-mac _require-windows _print-artifacts

help:
	@echo ""
	@echo "片刻 · Tauri 构建（当前平台: $(PLATFORM)）"
	@echo ""
	@echo "  make setup          uv sync + npm 依赖 + 图标"
	@echo "  make setup-python   仅 uv sync（无 .venv 时自动执行）"
	@echo "  make run            浏览器模式: uv run python app.py"
	@echo "  make dev            Tauri 桌面开发（uv sync → 独立窗口）"
	@echo "  make icons          从 desktop/app-icon.svg 生成各平台图标"
	@echo "  make check          检查 uv / .venv / Rust 环境"
	@echo "  make build          构建当前平台安装包"
	@echo "  make build-mac      构建 macOS .app（仅 macOS）"
	@echo "  make build-windows  构建 Windows 安装包（仅 Windows）"
	@echo "  make artifacts      显示构建产物路径"
	@echo "  make clean          删除 src-tauri/target"
	@echo ""
	@echo "环境变量 PIANKE_MODES=$(PIANKE_MODES)"
	@echo ""

setup: setup-python _npm-install icons
	@echo "✓ setup 完成"

setup-python: _ensure-uv
	@bash "$(ROOT)/scripts/bootstrap_python.sh"

icons: _npm-install
	cd "$(DESKTOP)" && $(NPM) run icon

check: setup-python _check-toolchain
	@echo "✓ 环境检查通过"

_check-toolchain:
	@echo "PIANKE_ROOT=$(PIANKE_ROOT)"
	@echo "PLATFORM=$(PLATFORM)"
	@command -v node >/dev/null || (echo "❌ 未找到 node"; exit 1)
	@command -v $(NPM) >/dev/null || (echo "❌ 未找到 npm"; exit 1)
	@test -x "$(UV)" || command -v uv >/dev/null || (echo "❌ 未找到 uv，见 https://docs.astral.sh/uv/"; exit 1)
	@echo "✓ uv: $$(command -v uv || echo $(UV))"
	@test -f "$(ROOT)/pyproject.toml" || (echo "❌ 未找到 pyproject.toml"; exit 1)
	@command -v $(CARGO) >/dev/null || (echo "❌ 未找到 cargo（请安装 Rust: https://rustup.rs）"; exit 1)
	@command -v rustc >/dev/null || (echo "❌ 未找到 rustc"; exit 1)
	@cd "$(TAURI_DIR)" && $(CARGO) --version && rustc --version
	@cd "$(TAURI_DIR)" && rustc --version | grep -qE 'rustc 1\.(8[8-9]|[9][0-9]|[1-9][0-9]{2,})' || \
		(echo "❌ Rust 版本过低，需要 >= 1.88"; \
		 echo "   请执行: cd desktop/src-tauri && rustup toolchain install 1.88"; exit 1)
	@test -f "$(ROOT)/app.py" || (echo "❌ 未找到 app.py"; exit 1)
	@test -x "$(PY_BIN)" || (echo "❌ .venv 未就绪，请 make setup-python"; exit 1)
	@echo "✓ .venv: $(PY_BIN)"

# 浏览器模式（与 make dev 共用同一套 uv/.venv）
run: setup-python
	@echo "→ uv run python app.py  (http://localhost:5057)"
	cd "$(ROOT)" && uv run python app.py

# Tauri 桌面开发：先 uv sync，再由 Rust 侧 uv run 拉起 Flask
dev: setup check
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  片刻 · Tauri 开发模式（Python: uv run / .venv）"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	cd "$(DESKTOP)" && $(NPM) run tauri dev

build:
ifeq ($(PLATFORM),mac)
	@$(MAKE) build-mac
else ifeq ($(PLATFORM),windows)
	@$(MAKE) build-windows
else
	@echo "❌ 当前平台 ($(UNAME_S)) 不支持自动构建，请使用 build-mac 或 build-windows"
	@exit 1
endif

build-mac: _require-mac setup check
	cd "$(DESKTOP)" && $(NPM) run tauri build
	@$(MAKE) _print-artifacts-mac

build-windows: _require-windows setup check
	cd "$(DESKTOP)" && $(NPM) run tauri build
	@$(MAKE) _print-artifacts-windows

clean:
	rm -rf "$(TAURI_DIR)/target"
	@echo "✓ 已清理 $(TAURI_DIR)/target"

artifacts:
ifeq ($(PLATFORM),mac)
	@$(MAKE) _print-artifacts-mac
else ifeq ($(PLATFORM),windows)
	@$(MAKE) _print-artifacts-windows
else
	@$(MAKE) _print-artifacts-mac 2>/dev/null || true
	@$(MAKE) _print-artifacts-windows 2>/dev/null || true
endif

# ---------- 内部 ----------

_ensure-uv:
	@command -v uv >/dev/null || test -x "$(HOME)/.local/bin/uv" || test -x "$(HOME)/.cargo/bin/uv" || \
		(echo "→ 将在 setup-python 中自动安装 uv")

_npm-install:
	@test -d "$(DESKTOP)/node_modules" || (echo "→ npm install ..." && cd "$(DESKTOP)" && $(NPM) install)

_require-mac:
	@test "$(PLATFORM)" = "mac" || (echo "❌ build-mac 必须在 macOS 上运行"; exit 1)

_require-windows:
	@test "$(PLATFORM)" = "windows" || (echo "❌ build-windows 必须在 Windows 上运行"; exit 1)

_print-artifacts-mac:
	@echo ""
	@echo "━━ macOS 构建产物 ━━"
	@find "$(TARGET_DIR)/macos" -maxdepth 1 -name "*.app" 2>/dev/null | while read -r app; do echo "  $$app"; done || \
		echo "  （未找到 .app，请先 make build-mac）"
	@echo ""

_print-artifacts-windows:
	@echo ""
	@echo "━━ Windows 构建产物 ━━"
	@find "$(TARGET_DIR)/nsis" -maxdepth 1 \( -name "*.exe" -o -name "*.msi" \) 2>/dev/null | while read -r f; do echo "  $$f"; done || true
	@find "$(TARGET_DIR)/msi" -maxdepth 1 -name "*.msi" 2>/dev/null | while read -r f; do echo "  $$f"; done || \
		echo "  （未找到安装包，请先 make build-windows）"
	@echo ""
