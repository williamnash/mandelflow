# Copy to terraform.tfvars and fill in for your project.
# terraform.tfvars is gitignored — never commit real values.

project_id   = "your-gcp-project-id"
region       = "us-central1"
zone         = "us-central1-a"
cluster_name = "mandelflow"

github_owner = "your-github-username"
github_repo  = "mandelflow"

# Must be globally unique. Convention: <project_id>-mandelflow-zarr
bucket_name = "your-gcp-project-id-mandelflow-zarr"

gpu_machine_type = "n1-standard-4"
gpu_node_count   = 1
