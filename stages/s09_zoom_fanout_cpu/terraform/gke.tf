# GKE Standard cluster with a CPU node pool (always created) and an optional
# GPU node pool. s09 uses the CPU pool only; s11 sets `gpu_node_count > 0` to
# add T4-equipped nodes for the GPU-kernel Pods.
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

# CPU pool. Autoscales 1..max during the run, scales back to 1 when idle
# so the cluster has somewhere to host system Pods (DNS, metrics-server,
# Dagster control plane if/when added) but isn't paying for fan-out
# capacity between runs.
#
# Each Pod requests 1–2 vCPU; e2-standard-2 fits one fan-out Pod plus a
# small amount of system overhead per node. With max 8 nodes we can run
# our default n_pods=8 with one Pod per node, in parallel.
resource "google_container_node_pool" "cpu_pool" {
  name     = "cpu-pool"
  cluster  = google_container_cluster.mandelflow.id
  location = var.region

  autoscaling {
    min_node_count = var.cpu_min_nodes
    max_node_count = var.cpu_max_nodes
  }

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
#
# Conditional: when `gpu_node_count == 0` (s09 default) the pool is not
# created, so the cluster carries no GPU cost. s11 sets the var to >= 1.
resource "google_container_node_pool" "gpu_pool" {
  count = var.gpu_node_count > 0 ? 1 : 0

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

  # TODO: autoscaling block. For demo, a fixed `var.gpu_node_count` is simpler.
  # For real batch fan-out, set min_node_count=0 and let cluster-autoscaler
  # scale to zero between runs.
}
