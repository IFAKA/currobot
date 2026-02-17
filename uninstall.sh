#!/usr/bin/env bash
# currobot — complete uninstall, no traces left
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.jobbot.backend.plist"
BROWSER_CACHE="$HOME/Library/Caches/ms-playwright"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "  $*"; }
success() { echo -e "${GREEN}  ✓${NC} $*"; }
warn()    { echo -e "${YELLOW}  !${NC} $*"; }

echo ""
echo -e "${RED}currobot uninstaller${NC}"
echo "This will remove currobot and all its data from your machine."
echo ""
read -r -p "Are you sure? This cannot be undone. [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }
echo ""

# 1. Stop and remove Launch Agent
if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  success "Launch Agent removed"
else
  info "Launch Agent not installed — skipping"
fi

# 2. Remove Playwright / Patchright browser cache
if [ -d "$BROWSER_CACHE" ]; then
  rm -rf "$BROWSER_CACHE"
  success "Browser cache removed ($BROWSER_CACHE)"
else
  info "Browser cache not found — skipping"
fi

# 3. Remove macOS Keychain entries
removed_keys=0
for service in jobbot currobot infojobs indeed; do
  while security delete-generic-password -s "$service" 2>/dev/null; do
    removed_keys=$((removed_keys + 1))
  done
done
if [ "$removed_keys" -gt 0 ]; then
  success "Removed $removed_keys Keychain entry/entries"
else
  info "No Keychain entries found — skipping"
fi

# 4. Delete the project folder (last step)
echo ""
warn "Deleting project folder: $SCRIPT_DIR"
read -r -p "  Confirm folder deletion [y/N] " confirm2
if [[ "$confirm2" =~ ^[Yy]$ ]]; then
  # Move up before deleting
  cd "$HOME"
  rm -rf "$SCRIPT_DIR"
  success "Project folder deleted"
else
  warn "Folder kept. Everything else has been cleaned up."
fi

echo ""
echo -e "${GREEN}currobot has been completely removed.${NC}"
echo ""
