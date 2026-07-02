terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
  }

  # Remote state in GCS (bucket created out-of-band with versioning enabled).
  # State is shared and persisted across environments via this backend.
  backend "gcs" {
    bucket = "gen-lang-client-0243034020-tfstate"
    prefix = "toddler-private-rag/terraform"
  }
}
