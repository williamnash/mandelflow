# GKE Standard cluster with two node pools:
# - A small default CPU pool for Dagster control plane / IO managers / scheduling
# - A GPU pool with T4s for the per-frame compute Pods
#
# We use Standard (not Autopilot) on purpose — Autopilot abstracts away the
# node-pool primitives, GPU taints, and Workload Identity wiring that this
# stage exists to teach. See docs/GOTCHAS.md #7.

resource "google_container_cluster" "mandelflow" {
  name     = var.cluster_name
  location = var.region

  # Recommended: separate the default node pool from the cluster definition so
  # we can manage GPU and CPU pools independently below.
  remove_default_node_pool = true
  initial_node_count       = 1

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = "REGULAR"
  }

  depends_on = [
    google_project_service.required_apis,
  ]
}

# Small CPU pool for Dagster control plane, IO Managers, and any non-compute Pods.
resource "google_container_node_pool" "cpu_pool" {
  name       = "cpu-pool"
  cluster    = google_container_cluster.mandelflow.id
  location   = var.region
  node_count = 1

  node_config {
    machine_type = "e2-standard-2"

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]
  }
}

# GPU pool. Zonal (T4s are zonal resources). Tainted so only GPU-tolerant
# Pods land here — the compute Pods spec includes the matching toleration.
resource "google_container_node_pool" "gpu_pool" {
  name       = "gpu-pool"
  cluster    = google_container_cluster.mandelflow.id
  location   = var.zone
  node_count = var.gpu_node_count

  node_config {
    machine_type = var.gpu_machine_type

    guest_accelerator {
      type  = "nvidia-tesla-t4"
      count = 1
    }

    # Keep non-GPU workloads off this expensive pool.
    taint {
      key    = "nvidia.com/gpu"
      value  = "present"
      effect = "NO_SCHEDULE"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]
  }

  # TODO(s08): autoscaling block. For demo, fixed `var.gpu_node_count` is simpler.
  # For real batch fan-out, set min_node_count=0 and let cluster-autoscaler
  # scale to zero between runs.
}
