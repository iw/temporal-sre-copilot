# ---------------------------------------------------------------------------
# DSQL — Monitored cluster
# ---------------------------------------------------------------------------

output "monitored_dsql_endpoint" {
  description = "Public endpoint for the monitored Aurora DSQL cluster"
  value       = "${aws_dsql_cluster.monitored.identifier}.dsql.${var.region}.on.aws"
}

# ---------------------------------------------------------------------------
# DSQL — Copilot cluster
# ---------------------------------------------------------------------------

output "copilot_dsql_endpoint" {
  description = "Public endpoint for the Copilot Aurora DSQL cluster"
  value       = "${aws_dsql_cluster.copilot.identifier}.dsql.${var.region}.on.aws"
}

# ---------------------------------------------------------------------------
# Bedrock Knowledge Base
# ---------------------------------------------------------------------------

output "knowledge_base_id" {
  description = "Bedrock Knowledge Base ID for RAG retrieval"
  value       = awscc_bedrock_knowledge_base.copilot.id
}

output "data_source_id" {
  description = "Bedrock Data Source ID for triggering ingestion"
  value       = awscc_bedrock_data_source.copilot_docs.data_source_id
}

output "kb_source_bucket" {
  description = "S3 bucket for KB source documents"
  value       = aws_s3_bucket.kb_source.bucket
}

output "profile_bucket" {
  description = "S3 bucket for behaviour profile storage"
  value       = aws_s3_bucket.profiles.bucket
}

# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------

output "region" {
  description = "AWS region"
  value       = var.region
}
