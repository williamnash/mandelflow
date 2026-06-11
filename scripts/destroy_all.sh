#!/usr/bin/env bash
# destroy_all.sh — tear down mandelflow cloud infrastructure in dependency
# order. Runs `terraform destroy` in each stage's terraform/ that has state.
#
# Safety:
#   - Prompts y/N before each destroy. Run with --yes to skip prompts.
#   - Destroys in dependency order (s09 GKE first, then s08 foundation).
#   - Stops on first non-zero terraform exit unless --keep-going is set.
#   - Calls scripts/audit_cloud.sh at the end so you see what (if anything)
#     remains. Some resources (orphan disks, manually-created buckets) won't
#     be in terraform state and need manual cleanup.
#
# Usage:
#   scripts/destroy_all.sh                # interactive, dependency-ordered
#   scripts/destroy_all.sh --yes          # non-interactive (CI / "just do it")
#   scripts/destroy_all.sh --keep-going   # continue past terraform errors

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AUTO_YES=0
KEEP_GOING=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) AUTO_YES=1 ;;
        --keep-going) KEEP_GOING=1 ;;
        --help|-h)
            sed -nE 's/^# ?//p' "$0" | head -25
            exit 0
            ;;
    esac
done

# Dependency order: destroy GKE-layer terraform BEFORE s08 foundation,
# because s09 references s08's bucket via data source (data sources don't
# create dependencies in state, but logically you don't want to delete the
# bucket while a cluster might still be using it).
DIRS=(
    "stages/s09_zoom_fanout_cpu/terraform"
    "stages/s08_zoom_cloud_cpu/terraform"
)

confirm() {
    [[ "$AUTO_YES" -eq 1 ]] && return 0
    read -r -p "$1 [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

for d in "${DIRS[@]}"; do
    path="$REPO_ROOT/$d"
    if [[ ! -f "$path/terraform.tfstate" ]] && [[ ! -d "$path/.terraform" ]]; then
        echo "▷ $d — no state, skipping."
        continue
    fi
    echo ""
    echo "▷ $d"
    pushd "$path" >/dev/null
    terraform state list 2>/dev/null | sed 's/^/    /' || true
    if ! confirm "  destroy this state?"; then
        echo "  skipped."
        popd >/dev/null
        continue
    fi
    if [[ "$AUTO_YES" -eq 1 ]]; then
        terraform destroy -auto-approve
    else
        terraform destroy
    fi
    rc=$?
    popd >/dev/null
    if [[ "$rc" -ne 0 ]] && [[ "$KEEP_GOING" -ne 1 ]]; then
        echo "  terraform destroy failed (exit $rc). Stopping. Pass --keep-going to continue."
        exit "$rc"
    fi
done

echo ""
echo "▷ Final audit:"
"$REPO_ROOT/scripts/audit_cloud.sh" || true
