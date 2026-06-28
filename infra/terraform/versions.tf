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

  # Optional remote state. Recommended once you adopt this config: create a GCS
  # bucket for state and uncomment the block below.
  #
  # backend "gcs" {
  #   bucket = "gen-lang-client-0243034020-tfstate"
  #   prefix = "toddler-private-rag/terraform"
  # }
}
