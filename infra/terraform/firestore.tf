# Production metadata database (DATABASE_TYPE=firestore). The default database
# is named "(default)". Importing an existing database is safe; Terraform will
# not recreate it.

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.services]
}
