# SSH access via Identity-Aware Proxy ONLY.
#
# IAP is GCP's identity-checking layer: clients connect to a TCP forwarder
# that requires both IAM authentication (a real GCP principal) and the
# `roles/iap.tunnelResourceAccessor` role. The forwarder itself sits inside
# a well-known source range that we whitelist here.
#
# The default network's `default-allow-ssh` rule (which permits SSH from
# 0.0.0.0/0) must be deleted separately — Terraform doesn't manage it:
#   gcloud compute firewall-rules delete default-allow-ssh
#
# After that, the only way onto the VM via SSH is:
#   gcloud compute ssh mandelflow-vm --zone <zone> --tunnel-through-iap
# which the gcloud SDK handles transparently.

resource "google_compute_firewall" "allow_iap_ssh" {
  name        = "allow-iap-ssh"
  network     = "default"
  description = "SSH from Identity-Aware Proxy only (replaces default-allow-ssh)."

  direction = "INGRESS"
  priority  = 1000

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # IAP's TCP-forwarder source range; documented at
  # https://cloud.google.com/iap/docs/using-tcp-forwarding
  source_ranges = ["35.235.240.0/20"]

  depends_on = [
    google_project_service.required_apis,
  ]
}
