#!/bin/sh
# foundry: kind=script domain=meta touches=registry
#
# Install a pre-commit hook that keeps .jos/components/snapshot.yaml in
# sync with the distributed per-pillar components.yaml files per
# JOS-SPEC-026 v1.1 post-commit-hook contract.
#
# CIP is file-authored: components live at docs/pillars/*/components.yaml.
# This hook fires when ANY pillar components.yaml is staged.
#
# Behavior on a triggered commit:
#   1. Re-run scripts/components_snapshot.py
#   2. Auto-stage the regenerated .jos/components/snapshot.yaml
#   3. Allow the commit to proceed
#
# No-op when nothing under docs/pillars/*/components.yaml is staged.
#
# Idempotent: re-running this installer does nothing if our marker is
# already present. Won't overwrite a pre-existing pre-commit hook —
# prints next-steps and exits non-zero.
#
# Usage:
#   sh scripts/install_components_hook.sh              # install
#   sh scripts/install_components_hook.sh --uninstall  # remove

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_FILE="$REPO_ROOT/.git/hooks/pre-commit"
MARKER="# JOS_COMPONENTS_HOOK v1 (per JOS-SPEC-026 v1.1)"

if [ "$1" = "--uninstall" ]; then
    if [ -f "$HOOK_FILE" ] && grep -q "$MARKER" "$HOOK_FILE" 2>/dev/null; then
        rm -f "$HOOK_FILE"
        echo "[install_components_hook] uninstalled $HOOK_FILE"
        exit 0
    fi
    echo "[install_components_hook] no JOS components hook found to uninstall"
    exit 0
fi

if [ -f "$HOOK_FILE" ] && grep -q "$MARKER" "$HOOK_FILE" 2>/dev/null; then
    echo "[install_components_hook] already installed; nothing to do"
    exit 0
fi

if [ -f "$HOOK_FILE" ]; then
    echo "[install_components_hook] ERROR: $HOOK_FILE already exists and is not a JOS components hook."
    echo "[install_components_hook] To integrate, add the snippet shown in this script's hook body to your existing hook."
    echo "Re-run with --uninstall first if you want this installer to take over."
    exit 1
fi

mkdir -p "$REPO_ROOT/.git/hooks"

cat > "$HOOK_FILE" <<HOOK_EOF
#!/bin/sh
$MARKER
# Installed by scripts/install_components_hook.sh.
# Keeps .jos/components/snapshot.yaml in sync with docs/pillars/*/components.yaml.

set -e

STAGED=\$(git diff --cached --name-only --diff-filter=ACM | \
    grep -E "^docs/pillars/[^/]+/components\.yaml\$" || true)

if [ -z "\$STAGED" ]; then
    exit 0
fi

echo "[jos:components] pillar components.yaml change detected; regenerating snapshot.yaml..."

REPO_ROOT="\$(git rev-parse --show-toplevel)"
cd "\$REPO_ROOT"

if command -v uv >/dev/null 2>&1; then
    uv run --quiet --with pyyaml python scripts/components_snapshot.py >/dev/null
else
    python scripts/components_snapshot.py >/dev/null
fi

if [ -f .jos/components/snapshot.yaml ]; then
    git add .jos/components/snapshot.yaml
    echo "[jos:components] snapshot.yaml regenerated + staged."
fi
HOOK_EOF

chmod +x "$HOOK_FILE"
echo "[install_components_hook] installed $HOOK_FILE"
echo "[install_components_hook] commits that touch docs/pillars/*/components.yaml will auto-regenerate snapshot.yaml"
