# -----------------------------------------------------------------------------
# Networking Module
# -----------------------------------------------------------------------------
# Security group and rules for Copilot services.
# -----------------------------------------------------------------------------

resource "aws_security_group" "copilot" {
  name        = "${var.project_name}-copilot"
  description = "Security group for Copilot services"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.project_name}-copilot" }
}

resource "aws_security_group_rule" "self" {
  type              = "ingress"
  from_port         = 0
  to_port           = 65535
  protocol          = "tcp"
  self              = true
  security_group_id = aws_security_group.copilot.id
  description       = "Allow all traffic within Copilot services"
}

resource "aws_security_group_rule" "egress_https" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.copilot.id
  description       = "Allow HTTPS egress for AWS APIs"
}

resource "aws_security_group_rule" "egress_loki" {
  type                     = "egress"
  from_port                = 3100
  to_port                  = 3100
  protocol                 = "tcp"
  source_security_group_id = var.loki_security_group_id
  security_group_id        = aws_security_group.copilot.id
  description              = "Allow egress to Loki for log queries"
}

resource "aws_security_group_rule" "egress_dsql" {
  type              = "egress"
  from_port         = 5432
  to_port           = 5432
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.copilot.id
  description       = "Allow egress to DSQL"
}

resource "aws_security_group_rule" "ingress_api" {
  type              = "ingress"
  from_port         = 8080
  to_port           = 8080
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.copilot.id
  description       = "Allow ingress to Copilot API from VPC"
}
