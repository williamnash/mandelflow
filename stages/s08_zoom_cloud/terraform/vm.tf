# GCE VM with a T4 GPU. Uses the Google "Deep Learning VM" image family
# which ships with NVIDIA drivers + Docker preinstalled — saves us from
# bootstrapping CUDA drivers ourselves on first boot. (Plain Ubuntu also
# works but adds ~5 min to first boot for driver install.)

resource "google_compute_instance" "mandelflow_vm" {
  name         = var.vm_name
  zone         = var.zone
  machine_type = var.machine_type

  # Preemptible / Spot brings cost to ~$0.12/hr but adds ~24h max lifetime
  # and risk of mid-run preemption. Off by default; flip on for cheaper
  # exploration runs.
  scheduling {
    on_host_maintenance = "TERMINATE"   # required for GPU VMs
    automatic_restart   = false
    # preemptible = true
  }

  guest_accelerator {
    type  = "nvidia-tesla-t4"
    count = 1
  }

  boot_disk {
    initialize_params {
      # Deep Learning VM with CUDA 12 + Docker baked in.
      image = "projects/deeplearning-platform-release/global/images/family/common-cu123-debian-11-py310"
      size  = var.boot_disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"

    # Ephemeral public IP for SSH access. Drop the access_config block to
    # make the VM private — but you'd then need IAP tunneling for SSH.
    access_config {}
  }

  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }

  # `pip3 install` and a sanity check that the GPU is visible. Real workflow
  # SSHes in and `docker run`s the mandelflow image; this is just to
  # confirm the box is healthy on first boot.
  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -eu
    echo "[mandelflow-vm] startup script began at $(date)"
    nvidia-smi || echo "[mandelflow-vm] WARN: nvidia-smi not yet available"
    echo "[mandelflow-vm] ready"
  EOT

  labels = {
    stage   = "s08"
    purpose = "mandelflow-demo"
  }

  depends_on = [
    google_project_service.required_apis,
  ]
}
