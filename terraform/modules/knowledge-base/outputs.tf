output "knowledge_base_id" {
  value = awscc_bedrock_knowledge_base.this.id
}

output "knowledge_base_arn" {
  value = awscc_bedrock_knowledge_base.this.knowledge_base_arn
}

output "data_source_id" {
  value = awscc_bedrock_data_source.docs.data_source_id
}

output "source_bucket" {
  value = aws_s3_bucket.source.bucket
}

output "vectors_bucket" {
  value = awscc_s3vectors_vector_bucket.kb.vector_bucket_name
}

output "index_arn" {
  value = awscc_s3vectors_index.kb.index_arn
}
