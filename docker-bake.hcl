variable "REGISTRY" {
  default = "ghcr.io/zerotymer"
}

variable "IMAGE" {
  default = "wikijs-gateway"
}

variable "TAG" {
  default = "latest"
}

group "default" {
  targets = ["gateway"]
}

# Local build: docker buildx bake
target "gateway" {
  context    = "."
  dockerfile = "Dockerfile"
  tags       = ["${REGISTRY}/${IMAGE}:${TAG}"]
}
