#!/bin/bash
#SBATCH --job-name=15c15b3c-3515-4fa0-b45c-efd4d94b7dd7
#SBATCH --output=/root/.local/interlink/jobs/default-15c15b3c-3515-4fa0-b45c-efd4d94b7dd7/job.out
#SBATCH --job-name=helloworld-pod
#SBATCH --cpus-per-task=1
#SBATCH --mem=1024

 /root/.local/interlink/jobs/default-15c15b3c-3515-4fa0-b45c-efd4d94b7dd7/mesh.sh /root/.local/interlink/jobs/default-15c15b3c-3515-4fa0-b45c-efd4d94b7dd7/job.sh