###############################################################################
# System Health Check API – Terraform root module
# Target: AWS (ECS Fargate + ALB + ECR + CloudWatch)
###############################################################################

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment to use S3 remote state (recommended for teams)
  # backend "s3" {
  #   bucket         = "your-tfstate-bucket"
  #   key            = "system-health-api/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region
}

# ── Data sources ────────────────────────────────────────────────────────────
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }

# ── Locals ──────────────────────────────────────────────────────────────────
locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
  account_id = data.aws_caller_identity.current.account_id
}

# ── ECR ─────────────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "api" {
  name                 = "${local.name_prefix}-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }

  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ── Networking ──────────────────────────────────────────────────────────────
module "networking" {
  source      = "./modules/networking"
  name_prefix = local.name_prefix
  common_tags = local.common_tags
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
  vpc_cidr    = var.vpc_cidr
}

# ── ECS / Fargate ───────────────────────────────────────────────────────────
module "ecs" {
  source       = "./modules/ecs"
  name_prefix  = local.name_prefix
  common_tags  = local.common_tags
  account_id   = local.account_id
  aws_region   = var.aws_region
  environment  = var.environment

  ecr_image_url  = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
  vpc_id         = module.networking.vpc_id
  public_subnets = module.networking.public_subnet_ids
  private_subnets = module.networking.private_subnet_ids
  alb_sg_id      = module.networking.alb_sg_id
  ecs_sg_id      = module.networking.ecs_sg_id

  desired_count     = var.desired_count
  cpu               = var.task_cpu
  memory            = var.task_memory
  log_group_name    = module.monitoring.log_group_name
}

# ── Monitoring ──────────────────────────────────────────────────────────────
module "monitoring" {
  source       = "./modules/monitoring"
  name_prefix  = local.name_prefix
  common_tags  = local.common_tags
  ecs_service_name  = module.ecs.service_name
  ecs_cluster_name  = module.ecs.cluster_name
  alb_arn_suffix    = module.ecs.alb_arn_suffix
  target_group_arn_suffix = module.ecs.target_group_arn_suffix
  alarm_email       = var.alarm_email
}
