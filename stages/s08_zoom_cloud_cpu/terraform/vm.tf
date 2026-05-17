# GCE VM running the mandelflow container.
#
# CURRENT MODE: CPU-only. The project's GPU quota request was denied
# (new-project policy — wait 48h or seasoning required). Until then, we
# deploy a CPU-only e2-standard-2 running s03's numba kernel and validate
# the rest of the pipeline. The diff to flip back to GPU is small:
#   - restore `guest_accelerator` block
#   - machine_type → "n1-standard-4"
#   - image → "common-cu129-ubuntu-2204-nvidia-580" (DLVM)
#   - scheduling.on_host_maintenance → "TERMINATE"
#   - stages/s08_zoom_cloud/compute.py → import from s06_gpu_shader

resource "google_compute_instance" "mandelflow_vm" {
  name         = var.vm_name
  zone         = var.zone
  machine_type = var.machine_type

  scheduling {
    on_host_maintenance = "MIGRATE"   # CPU VMs can live-migrate
    automatic_restart   = true
  }

  # GPU block deliberately omitted while quota is denied. Restore when
  # GPUS_ALL_REGIONS quota is granted; see top-of-file comment.

  boot_disk {
    initialize_params {
      # Container-Optimized OS: minimal Linux image with Docker preinstalled,
      # purpose-built for running containers. Smaller than Ubuntu LTS, faster
      # boot, hardened for the container workload — no apt-installing things.
      image = "projects/cos-cloud/global/images/family/cos-stable"
      size  = var.boot_disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"
    # No `access_config` block = no public IP. SSH is via IAP tunnel only;
    # the firewall in firewall.tf allows TCP/22 from the IAP source range.
  }

  service_account {
    email = google_service_account.vm.email
    # Narrow OAuth scopes (defense-in-depth alongside IAM bindings):
    #   - devstorage.read_write: write Zarrs to our bucket
    #   - logging.write:         stream container stdout to Cloud Logging
    #   - cloud-platform.read-only: read images from Artifact Registry
    scopes = [
      "https://www.googleapis.com/auth/devstorage.read_write",
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/cloud-platform.read-only",
    ]
  }

  # COS has `docker-credential-gcr` preinstalled. Configure it to provide
  # tokens for our Artifact Registry region. After this runs, `docker pull`
  # from us-central1-docker.pkg.dev works using the VM's attached SA — no
  # JSON keys, no manual auth.
  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -eu
    echo "[mandelflow-vm] startup at $(date)"
    docker-credential-gcr configure-docker --registries=us-central1-docker.pkg.dev
    echo "[mandelflow-vm] docker creds configured for us-central1-docker.pkg.dev"
  EOT

  labels = {
    stage   = "s08"
    purpose = "mandelflow-demo"
  }

  depends_on = [
    google_project_service.required_apis,
  ]
}
