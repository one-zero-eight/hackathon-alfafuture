FROM golang:1.27.3-alpine3.24@sha256:b8c9b82affbbb82a020bbcf998dad2ba9516944ac7e883524642a481a9505e9c AS build

WORKDIR /src
ENV GOTOOLCHAIN=local
COPY collector/go.mod collector/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY collector/ .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -p=2 -trimpath -ldflags="-s -w" -o /out/news ./cmd/news

FROM alpine:3.24.3@sha256:b3413572228e34bd1c9245f5565e6cd127005655e8a7899aef33d8e83255c9e6

WORKDIR /app
COPY --from=build /out/news /usr/local/bin/news
# The curated source list and the Google News topics are plain files: mount your own over them to change the list without a rebuild.
COPY collector/sources.json collector/topics.txt /app/
USER 65532:65532
ENV HTTP_ADDR=0.0.0.0:8080
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-Y", "off", "--spider", "-T", "3", "http://127.0.0.1:8080/readyz"]
ENTRYPOINT ["/usr/local/bin/news"]
