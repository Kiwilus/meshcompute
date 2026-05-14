# docker/Dockerfile
FROM golang:1.21-alpine AS builder

WORKDIR /app
COPY server/go.mod server/go.sum ./
RUN go mod download
COPY server/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -o /meshserver

FROM alpine:latest
RUN apk --no-cache add ca-certificates
COPY --from=builder /meshserver /meshserver
EXPOSE 8080
ENTRYPOINT ["/meshserver"]