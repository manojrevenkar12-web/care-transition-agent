# The LLM egress gateway: Go standard library only, a static binary on a distroless base.
#   docker build -f deploy/docker/gateway.Dockerfile -t cta-gateway .
FROM golang:1.24.7-alpine AS build
WORKDIR /src
COPY gateway/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/gateway ./cmd/gateway

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/gateway /gateway
COPY config/gateway.json /config/gateway.json
USER nonroot
EXPOSE 8070
ENTRYPOINT ["/gateway", "-config", "/config/gateway.json"]
