# Copy to terraform.tfvars and fill in for your project.
# terraform.tfvars is gitignored — never commit real values.

project_id = "your-gcp-project-id"
region     = "us-central1"
zone       = "us-central1-a"

vm_name      = "mandelflow-vm"
machine_type = "n1-standard-4"

# Must be globally unique. Convention: <project_id>-mandelflow-zarr
bucket_name = "your-gcp-project-id-mandelflow-zarr"

# Find via: gcloud billing accounts list
billing_account = "01ABCD-EFGH12-IJKLMN"
