.PHONY: build test clean build-gostats build-goppstats build-dashgen

build: build-gostats build-goppstats build-dashgen

build-gostats:
	go build -o bin/gostats ./cmd/gostats/

build-goppstats:
	go build -o bin/goppstats ./cmd/goppstats/

build-dashgen:
	go build -o bin/dashgen ./cmd/dashgen/

test:
	go test -v ./cmd/gostats/...
	go test -v ./cmd/goppstats/...

clean:
	rm -rf bin/
