#!/usr/bin/env bash
# audit_cloud.sh — list every GCP resource in the project that could be billing.
#
# Run before bringing up cloud infra (to see what's already there) and after
# `terraform destroy` (to confirm nothing leaked). Exits 0 if no obviously
# billing resources exist; 1 otherwise. Non-zero exit is just a hint — read
# the output and judge.
#
# Usage:
#   scripts/audit_cloud.sh                # uses current gcloud default project
#   scripts/audit_cloud.sh <project_id>   # override
#
# Resources checked, grouped by cost model:
#
#   ALWAYS-BILLING (worth acting on)
#     GKE clusters             — control plane ~$0.10/hr always-on
#     GKE node pool sizes      — billed per running node
#     GCE VMs (running)        — e2-standard-2 ~$0.07/hr
#     Persistent disks         — ~$0.04/GB/month, linger after VM delete
#     Reserved static IPs      — ~$0.01/hr if unattached
#     Forwarding rules / LBs   — ~$18/month per rule (the classic leak)
#     Cloud SQL instances      — ~$0.05/hr+, can't scale to zero
#     Memorystore instances    — ~$0.04/hr+
#
#   INVENTORY ONLY (negligible/scale-to-zero, listed for visibility)
#     Cloud Run jobs/services  — free idle
#     GCS buckets              — pennies; contents may matter
#     Artifact Registry repos  — pennies
#     Cloud Build (running)    — transient
#
# Disabled-API responses are treated as "no resources" — the more accurate
# interpretation when you haven't used that service.

set -uo pipefail

PROJECT="${1:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "$PROJECT" ]]; then
    echo "ERROR: no project_id supplied and no gcloud default set." >&2
    echo "Run: gcloud config set project <id>  OR pass as first arg." >&2
    exit 2
fi

if [[ -t 1 ]]; then
    R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; B='\033[1;34m'; D='\033[2m'; NC='\033[0m'
else
    R=''; G=''; Y=''; B=''; D=''; NC=''
fi

billing_count=0

section() {
    echo ""
    echo -e "${B}===== $1 =====${NC}"
}

# Run a gcloud command. Output:
#   "  none" (green) if no resources or API disabled
#   the tabular output (yellow) otherwise.
# Disabled-API responses (SERVICE_DISABLED) are treated as zero.
# Stdin is closed so any prompt ("enable API?") gets the default no-answer.
check() {
    local cmd="$1"
    local count_resources="${2:-1}"   # set to 0 for inventory-only sections
    local output
    output=$(eval "$cmd" 2>&1 </dev/null) || true
    # Recognise "service not enabled" responses — treat as "nothing here".
    if echo "$output" | grep -qE "(SERVICE_DISABLED|has not been used in project|API has not been used|not enabled)"; then
        echo -e "  ${G}none${NC} ${D}(API not enabled — no resources of this kind)${NC}"
        return
    fi
    # Strip header line, count non-empty lines = approximate row count.
    local n
    n=$(echo "$output" | tail -n +2 | grep -cv '^[[:space:]]*$' || true)
    if [[ -z "$output" ]] || [[ "$n" -eq 0 ]]; then
        echo -e "  ${G}none${NC}"
        return
    fi
    if [[ "$count_resources" -eq 1 ]]; then
        billing_count=$((billing_count + n))
    fi
    echo -e "${Y}$output${NC}"
}

echo -e "${B}Auditing project: ${NC}$PROJECT"
echo "Date: $(date)"

echo ""
echo -e "${D}── Always-billing resources ──────────────────────────────────────${NC}"

section "GKE clusters (control plane ~\$0.10/hr always-on)"
check "gcloud container clusters list --project=$PROJECT --format='table(name,location,status,currentNodeCount,currentMasterVersion)'"

section "GKE node pools (per-node billing)"
clusters=$(gcloud container clusters list --project=$PROJECT --format='value(name,location)' 2>/dev/null)
if [[ -n "$clusters" ]]; then
    while IFS=$'\t' read -r cname cloc; do
        [[ -z "$cname" ]] && continue
        echo "  cluster $cname ($cloc):"
        gcloud container node-pools list \
            --project=$PROJECT --cluster="$cname" --location="$cloc" \
            --format='table[no-heading](name,initialNodeCount,autoscaling.minNodeCount,autoscaling.maxNodeCount,config.machineType)' \
            2>/dev/null | sed 's/^/    /'
    done <<< "$clusters"
else
    echo -e "  ${G}no clusters to inspect${NC}"
fi

section "GCE VM instances (running) — \$0.05–0.40/hr each"
check "gcloud compute instances list --project=$PROJECT --filter='status:RUNNING' --format='table(name,zone.basename(),machineType.basename(),status)'"

section "GCE VM instances (stopped) — disk charges only"
check "gcloud compute instances list --project=$PROJECT --filter='status:TERMINATED' --format='table(name,zone.basename(),machineType.basename(),status)'"

section "Persistent disks (~\$0.04/GB/month — linger after VM delete)"
check "gcloud compute disks list --project=$PROJECT --format='table(name,zone.basename(),sizeGb,status,users.basename())'"

section "Reserved static IPs (~\$0.01/hr if unattached)"
check "gcloud compute addresses list --project=$PROJECT --format='table(name,region.basename(),address,status,users.basename())'"

section "Forwarding rules (load balancers — ~\$18/mo per rule, classic leak)"
check "gcloud compute forwarding-rules list --project=$PROJECT --format='table(name,region.basename(),IPAddress,target)'"

section "Cloud SQL instances (~\$0.05/hr+)"
check "gcloud sql instances list --project=$PROJECT --format='table(name,databaseVersion,region,state)'"

section "Memorystore Redis (~\$0.04/hr+)"
check "gcloud redis instances list --project=$PROJECT --region=us-central1 --format='table(name,tier,memorySizeGb,state)'"

echo ""
echo -e "${D}── Inventory only (free idle / negligible cost) ──────────────────${NC}"

section "Cloud Run jobs"
check "gcloud run jobs list --project=$PROJECT --region=us-central1 --format='table(JOB,REGION,LAST_EXECUTION_STATUS:label=LAST,CREATED_BY)'" 0

section "Cloud Run services"
check "gcloud run services list --project=$PROJECT --region=us-central1 --format='table(SERVICE,REGION,URL,LAST_DEPLOYED_BY)'" 0

section "GCS buckets"
check "gcloud storage buckets list --project=$PROJECT --format='table(name,location,storage_class)'" 0

section "Artifact Registry repositories"
check "gcloud artifacts repositories list --project=$PROJECT --format='table(name,format,location)'" 0

section "Cloud Build (currently running)"
check "gcloud builds list --project=$PROJECT --filter='status:WORKING OR status:QUEUED' --format='table(id,status,createTime,duration)'" 0

section "Summary"
if [[ "$billing_count" -eq 0 ]]; then
    echo -e "  ${G}✓ no always-billing resources found.${NC}"
    exit 0
fi
echo -e "  ${Y}~$billing_count always-billing items above.${NC}"
echo "  Read the output and judge — disks for stopped VMs are usually fine;"
echo "  GKE clusters, running VMs, LBs, unattached static IPs need action."
exit 1
