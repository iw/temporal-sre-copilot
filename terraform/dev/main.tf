# Ephemeral dev infrastructure — two DSQL clusters, Bedrock KB, S3 buckets.
#
# Provisions all AWS resources needed for local Copilot development:
#   - Monitored DSQL cluster (observed by the Copilot)
#   - Copilot DSQL cluster (Copilot's own state store and workflow persistence)
#   - Bedrock Knowledge Base with S3 Vectors for RAG retrieval
#   - S3 source bucket for KB documents
#   - IAM roles for Bedrock KB access
#
# Usage:
#   copilot dev infra apply
#   copilot dev infra destroy

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 1.0"
    }
  }
}

provider "aws" {
  region = var.region
}

provider "awscc" {
  region = var.region
}

data "aws_caller_identity" "current" {}

locals {
  kb_vector_bucket_name = "${var.project_name}-copilot-kb-vectors"
  profile_bucket_name   = "${var.project_name}-copilot-profiles"
  tags = {
    Lifecycle = "ephemeral"
    ManagedBy = "terraform"
    Project   = var.project_name
  }
}

# ---------------------------------------------------------------------------
# Aurora DSQL cluster — Monitored Temporal cluster persistence
# ---------------------------------------------------------------------------
resource "aws_dsql_cluster" "monitored" {
  deletion_protection_enabled = false

  tags = merge(local.tags, {
    Name = "${var.project_name}-monitored-dsql"
  })
}

# ---------------------------------------------------------------------------
# Aurora DSQL cluster — Copilot state store and workflow persistence
# ---------------------------------------------------------------------------
resource "aws_dsql_cluster" "copilot" {
  deletion_protection_enabled = false

  tags = merge(local.tags, {
    Name = "${var.project_name}-copilot-dsql"
  })
}

# ---------------------------------------------------------------------------
# Bedrock Knowledge Base — RAG for health explanations
# ---------------------------------------------------------------------------

# IAM role for Bedrock KB service
resource "aws_iam_role" "bedrock_kb" {
  name = "${var.project_name}-copilot-bedrock-kb"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })

  tags = merge(local.tags, { Name = "${var.project_name}-copilot-bedrock-kb" })
}

# S3 bucket — source documents
resource "aws_s3_bucket" "kb_source" {
  bucket = "${var.project_name}-copilot-kb-source"
  tags   = merge(local.tags, { Name = "${var.project_name}-copilot-kb-source" })
}

resource "aws_s3_bucket_versioning" "kb_source" {
  bucket = aws_s3_bucket.kb_source.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "kb_source" {
  bucket = aws_s3_bucket.kb_source.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "kb_source" {
  bucket                  = aws_s3_bucket.kb_source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_notification" "kb_source" {
  bucket      = aws_s3_bucket.kb_source.id
  eventbridge = true
}

# S3 Vectors — vector bucket and index
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

# IAM policies for Bedrock KB role
resource "aws_iam_role_policy" "kb_source" {
  name = "bedrock-kb-source"
  role = aws_iam_role.bedrock_kb.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.kb_source.arn, "${aws_s3_bucket.kb_source.arn}/*"]
    }]
  })
}

resource "aws_iam_role_policy" "kb_vectors" {
  name = "bedrock-kb-vectors"
  role = aws_iam_role.bedrock_kb.id

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
  role = aws_iam_role.bedrock_kb.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:aws:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"
    }]
  })
}

# Bedrock Knowledge Base (awscc provider for S3 Vectors support)
resource "awscc_bedrock_knowledge_base" "copilot" {
  name        = "${var.project_name}-copilot-kb"
  description = "Knowledge base for Temporal SRE Copilot RAG retrieval"
  role_arn    = aws_iam_role.bedrock_kb.arn

  knowledge_base_configuration = {
    type = "VECTOR"
    vector_knowledge_base_configuration = {
      embedding_model_arn = "arn:aws:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"
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

# ---------------------------------------------------------------------------
# S3 bucket — Behaviour Profile storage
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "profiles" {
  bucket = local.profile_bucket_name
  tags   = merge(local.tags, { Name = local.profile_bucket_name })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "profiles" {
  bucket = aws_s3_bucket.profiles.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "profiles" {
  bucket                  = aws_s3_bucket.profiles.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Bedrock Data Source — S3 documents
resource "awscc_bedrock_data_source" "copilot_docs" {
  knowledge_base_id = awscc_bedrock_knowledge_base.copilot.id
  name              = "copilot-documentation"
  description       = "Documentation sources for Temporal SRE Copilot"

  data_source_configuration = {
    type = "S3"
    s3_configuration = {
      bucket_arn = aws_s3_bucket.kb_source.arn
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
