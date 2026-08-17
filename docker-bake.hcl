variable "REGISTRY" {
  default = "ghcr.io/zerotymer"
}

variable "IMAGE" {
  default = "wikijs-agent-gateway"
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

# Registry push: docker buildx bake push --push
target "push" {
  inherits  = ["gateway"]
  platforms = ["linux/amd64", "linux/arm64"]
  # ponytail: no cache-from/to; add registry cache if CI builds get slow
}
