# Cloud Billing budget with email alerts at 20% / 100% of $50.
#
# Sends email to the billing account's IAM admins (you, by default) at the
# threshold percentages below. No teardown required — the budget is on the
# project, not on resources; it disappears when the project does.
#
# Requires `billingbudgets.googleapis.com` enabled and `roles/billing.user`
# on the billing account for whoever runs `terraform apply`. Both are
# already true for the account that created this project.

resource "google_billing_budget" "mandelflow_cap" {
  billing_account = var.billing_account
  display_name    = "mandelflow-2026 monthly $50 cap"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "50"
    }
  }

  # 20% = $10. First nudge.
  threshold_rules {
    threshold_percent = 0.2
    spend_basis       = "CURRENT_SPEND"
  }

  # 100% = $50. The "you forgot to terraform destroy" alarm.
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }

  all_updates_rule {
    # Sends to billing-account admins (the project owner) by default.
    # disable_default_iam_recipients = false is the implicit default.
    monitoring_notification_channels = []
  }

  depends_on = [
    google_project_service.required_apis,
  ]
}
