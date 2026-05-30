# One ECR repo per image. The worker reuses the ingest image, so there are 6.
locals {
  ecr_repos = ["gateway", "ingest", "search", "qpaper", "viva", "frontend"]
}

resource "aws_ecr_repository" "this" {
  for_each             = toset(local.ecr_repos)
  name                 = "${var.project}/${each.value}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = !local.is_prod

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep the last 20 images per repo.
resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 20 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}
