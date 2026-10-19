variable "aws_region" {
  type    = string
  default = "eu-north-1"
}
variable "project_name" {
  type    = string
  default = "portfolio-ops"
}
variable "monitored_instance_id" {
  description = "An existing EC2 instance ID in this AWS region."
  type        = string
  validation {
    condition     = can(regex("^i-([0-9a-f]{8}|[0-9a-f]{17})$", var.monitored_instance_id))
    error_message = "Provide a valid EC2 instance ID, such as i-0123456789abcdef0."
  }
}
variable "enable_reboot" {
  description = "Explicit opt-in: allows an EC2 reboot if the target instance is tagged PortfolioRemediation=allow."
  type        = bool
  default     = false
}
variable "notification_email" {
  type     = string
  default  = null
  nullable = true
}
