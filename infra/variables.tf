variable "aws_region" {
  description = "Región de AWS donde se despliega toda la infraestructura del proyecto."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Nombre corto del proyecto"
  type        = string
  default     = "end-to-end-model-uplift"
}

variable "environment" {
  description = "Entorno de despliegue (dev/staging/prod)."
  type        = string
  default     = "dev"
}
