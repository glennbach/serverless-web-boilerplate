# The API image for Lambda: the Go server plus the Lambda Web Adapter.
# Outside Lambda the adapter does not start, and /server runs on its own.
# Build: docker build --platform linux/arm64 -t proof-api api

FROM --platform=$BUILDPLATFORM golang:1.27 AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags="-s -w" -o /out/server .

FROM gcr.io/distroless/static-debian12:nonroot
# Lambda ignores USER and runs as its own user, which cannot enter the base
# image's WORKDIR (/home/nonroot, mode 0700): /server then fails to start.
WORKDIR /
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=build /out/server /server
ENTRYPOINT ["/server"]
