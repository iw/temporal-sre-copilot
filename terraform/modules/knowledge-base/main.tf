# -----------------------------------------------------------------------------
# Knowledge Base Module
# -----------------------------------------------------------------------------
# S3 source bucket, S3 Vectors (vector bucket + index), Bedrock Knowledge Base,
# and data source for RAG.
# Uses awscc provider for S3 Vectors and Bedrock KB support.
# -----------------------------------------------------------------------------

locals {
  kb_vector_bucket_name = "${var.project_name}-copilot-kb-vectors"
}

# -----------------------------------------------------------------------------
# S3 Bucket - Source Documents
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "source" {
  bucket = "${var.project_name}-copilot-kb-source"
  tags   = { Name = "${var.project_name}-copilot-kb-source" }
}

resource "aws_s3_bucket_versioning" "source" {
  bucket = aws_s3_bucket.source.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "source" {
  bucket                  = aws_s3_bucket.source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_notification" "source" {
  bucket      = aws_s3_bucket.source.id
  eventbridge = true
}

# -----------------------------------------------------------------------------
# S3 Vectors - Vector Bucket and Index
# -----------------------------------------------------------------------------

resource "awscc_s3vectors_vector_bucket" "kb" {
  vector_bucket_name = local.kb_vector_bucket_name
}

resource "awscc_s3vectors_index" "kb" {
  vector_bucket_arn = awscc_s3vectors_vector_bucket.kb.vector_bucket_arn
  index_name        = "${var.project_name}-copilot-kb-index"
  data_type         = "float32"
  dimension         = 1024 # Titan Embed Text V2
  distance_metric   = "cosine"

  # Bedrock stores chunk text and metadata in AMAZON_BEDROCK_TEXT and
  # AMAZON_BEDROCK_METADATA fields. By default both are filterable (2KB limit).
  # Moving them to non-filterable uses the 40KB total metadata budget instead,
  # preventing ingestion failures on larger chunks.
  metadata_configuration = {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
  }
}

# -----------------------------------------------------------------------------
# IAM Policies for Bedrock KB Role
# -----------------------------------------------------------------------------

resource "aws_iam_role_policy" "kb_source" {
  name = "bedrock-kb-source"
  role = var.bedrock_kb_role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.source.arn, "${aws_s3_bucket.source.arn}/*"]
    }]
  })
}

resource "aws_iam_role_policy" "kb_vectors" {
  name = "bedrock-kb-vectors"
  role = var.bedrock_kb_role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3vectors:CreateIndex", "s3vectors:DeleteIndex", "s3vectors:GetIndex",
          "s3vectors:ListIndexes", "s3vectors:PutVectors", "s3vectors:GetVectors",
          "s3vectors:DeleteVectors", "s3vectors:QueryVectors"
        ]
        Resource = [
          awscc_s3vectors_vector_bucket.kb.vector_bucket_arn,
          "${awscc_s3vectors_vector_bucket.kb.vector_bucket_arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "kb_embeddings" {
  name = "bedrock-kb-embeddings"
  role = var.bedrock_kb_role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
    }]
  })
}

# -----------------------------------------------------------------------------
# Bedrock Knowledge Base (awscc provider)
# -----------------------------------------------------------------------------

resource "awscc_bedrock_knowledge_base" "this" {
  name        = "${var.project_name}-copilot-kb"
  description = "Knowledge base for Temporal SRE Copilot RAG retrieval"
  role_arn    = var.bedrock_kb_role_arn

  knowledge_base_configuration = {
    type = "VECTOR"
    vector_knowledge_base_configuration = {
      embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }

  storage_configuration = {
    type = "S3_VECTORS"
    s3_vectors_configuration = {
      index_arn = awscc_s3vectors_index.kb.index_arn
    }
  }

  tags = { Name = "${var.project_name}-copilot-kb" }
}

resource "awscc_bedrock_data_source" "docs" {
  knowledge_base_id = awscc_bedrock_knowledge_base.this.id
  name              = "copilot-documentation"
  description       = "Documentation sources for Temporal SRE Copilot"

  data_source_configuration = {
    type = "S3"
    s3_configuration = {
      bucket_arn = aws_s3_bucket.source.arn
    }
  }

  vector_ingestion_configuration = {
    chunking_configuration = {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration = {
        max_tokens         = 512
        overlap_percentage = 20
      }
    }
  }
}
