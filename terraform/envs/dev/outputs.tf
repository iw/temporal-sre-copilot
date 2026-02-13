# -----------------------------------------------------------------------------
# Dev Environment Outputs
# -----------------------------------------------------------------------------

output "cluster_name" {
  value = module.ecs_cluster.cluster_name
}

output "cluster_arn" {
  value = module.ecs_cluster.cluster_arn
}

output "security_group_id" {
  value = module.networking.security_group_id
}

output "temporal_service_name" {
  value = module.temporal_server.service_name
}

output "worker_service_name" {
  value = module.worker.service_name
}

output "api_service_name" {
  value = module.api.service_name
}

output "api_endpoint" {
  value = "http://copilot-api:8080"
}

output "kb_source_bucket" {
  value = module.knowledge_base.source_bucket
}

output "knowledge_base_id" {
  value = module.knowledge_base.knowledge_base_id
}

output "copilot_task_role_arn" {
  value = module.iam.copilot_task_role_arn
}
