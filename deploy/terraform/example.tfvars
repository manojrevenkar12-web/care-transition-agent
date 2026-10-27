environment     = "staging"
tenants         = ["klinikum-nord", "st-elisabeth"]
agent_image     = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/cta-agent:latest"
gateway_image   = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/cta-gateway:latest"
certificate_arn = "arn:aws:acm:eu-central-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
allowed_cidrs   = ["10.0.0.0/8"]
