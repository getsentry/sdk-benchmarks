FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY main.go ./
RUN go build -o fakerelay .

FROM alpine:3.19
COPY --from=builder /app/fakerelay /usr/local/bin/
EXPOSE 5000
CMD ["fakerelay"]
