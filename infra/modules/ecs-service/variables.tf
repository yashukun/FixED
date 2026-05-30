variable "name" { type = string }
variable "cluster_arn" { type = string }
variable "cluster_name" { type = string }
variable "region" { type = string }

variable "image" { type = string }
variable "cpu" { type = number }
variable "memory" { type = number }
variable "container_port" {
  description = "Listening port; 0 for the worker (no port)."
  type        = number
  default     = 8000
}
variable "command" {
  description = "Optional container command override (e.g. the Celery worker)."
  type        = list(string)
  default     = []
}

variable "environment" {
  type    = map(string)
  default = {}
}
variable "secrets" {
  description = "Map of env var name -> Secrets Manager/SSM ARN."
  type        = map(string)
  default     = {}
}

variable "execution_role_arn" { type = string }
variable "task_role_arn" { type = string }

variable "subnets" { type = list(string) }
variable "security_groups" { type = list(string) }

# ---- Service Connect ----
variable "namespace_arn" {
  description = "Service Connect namespace ARN; empty disables Service Connect."
  type        = string
  default     = ""
}
variable "advertise_name" {
  description = "Port mapping name to advertise via Service Connect (backends only)."
  type        = string
  default     = ""
}
variable "dns_name" {
  description = "Service Connect client alias clients use (defaults to name)."
  type        = string
  default     = ""
}

# ---- ALB ----
variable "alb_target_group_arn" {
  type    = string
  default = ""
}

# ---- Scaling ----
variable "desired_count" { type = number }
variable "min_capacity" { type = number }
variable "max_capacity" { type = number }
variable "enable_autoscaling" {
  type    = bool
  default = true
}
variable "cpu_target" {
  type    = number
  default = 60
}

variable "health_command" {
  description = "ECS container healthCheck command (CMD-style list); empty skips it."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  type    = number
  default = 30
}
