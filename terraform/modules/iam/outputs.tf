output "ecs_execution_role_arn" {
  value = aws_iam_role.ecs_execution.arn
}

output "copilot_task_role_arn" {
  value = aws_iam_role.copilot_task.arn
}

output "bedrock_kb_role_arn" {
  value = aws_iam_role.bedrock_kb.arn
}

output "bedrock_kb_role_id" {
  value = aws_iam_role.bedrock_kb.id
}
