# Copy to terraform.tfvars and fill in for your project.
# terraform.tfvars is gitignored — never commit real values.

project_id   = "your-gcp-project-id"
region       = "us-central1"
zone         = "us-central1-a"
cluster_name = "mandelflow"

github_owner = "your-github-username"
github_repo  = "mandelflow"

# Bucket is owned by s08's terraform; this is a data-source lookup.
# Set to the same value used in stages/s08_zoom_cloud_cpu/terraform/terraform.tfvars.
bucket_name = "your-gcp-project-id-mandelflow-zarr"

# CPU node pool autoscaling. min stays at 1 for the system Pods;
# max should be >= MANDELFLOW_N_PODS for the largest workload you plan to run.
cpu_min_nodes = 1
cpu_max_nodes = 8

# Default 0 = CPU-only cluster (s09).
# Set to 1+ to add the T4 GPU pool (s11). T4 quota in `zone` is required.
gpu_node_count   = 0
gpu_machine_type = "n1-standard-4"
