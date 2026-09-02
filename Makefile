.PHONY: build test clean build-gostats build-goppstats build-goquotas build-dashgen \
        install install-systemd uninstall

PREFIX     ?= /usr/local
BINDIR     ?= $(PREFIX)/bin
SYSCONFDIR ?= /etc
CONFDIR     = $(SYSCONFDIR)/powerscale-data-insights
SYSTEMDDIR ?= /etc/systemd/system

build: build-gostats build-goppstats build-goquotas build-dashgen

build-gostats:
	go build -o bin/gostats ./cmd/gostats/

build-goppstats:
	go build -o bin/goppstats ./cmd/goppstats/

build-goquotas:
	go build -o bin/goquotas ./cmd/goquotas/

build-dashgen:
	go build -o bin/dashgen ./cmd/dashgen/

test:
	go test -v ./...

clean:
	rm -rf bin/

# Install binaries and example configs.
# Actual configs (gostats.toml, goppstats.toml, goquotas.toml) are only written if they do
# not already exist, so repeated installs do not overwrite a running config.
install: build
	install -d $(DESTDIR)$(BINDIR)
	install -m 755 bin/gostats bin/goppstats bin/goquotas bin/dashgen $(DESTDIR)$(BINDIR)/
	install -d $(DESTDIR)$(CONFDIR)
	install -m 644 configs/gostats.example.toml $(DESTDIR)$(CONFDIR)/gostats.example.toml
	install -m 644 configs/goppstats.example.toml $(DESTDIR)$(CONFDIR)/goppstats.example.toml
	install -m 644 configs/goquotas.example.toml $(DESTDIR)$(CONFDIR)/goquotas.example.toml
	@if [ ! -f $(DESTDIR)$(CONFDIR)/gostats.toml ]; then \
		install -m 640 configs/gostats.example.toml $(DESTDIR)$(CONFDIR)/gostats.toml; \
		echo "Installed starter config: $(DESTDIR)$(CONFDIR)/gostats.toml — edit before use"; \
	else \
		echo "$(DESTDIR)$(CONFDIR)/gostats.toml exists, skipping"; \
	fi
	@if [ ! -f $(DESTDIR)$(CONFDIR)/goppstats.toml ]; then \
		install -m 640 configs/goppstats.example.toml $(DESTDIR)$(CONFDIR)/goppstats.toml; \
		echo "Installed starter config: $(DESTDIR)$(CONFDIR)/goppstats.toml — edit before use"; \
	else \
		echo "$(DESTDIR)$(CONFDIR)/goppstats.toml exists, skipping"; \
	fi
	@if [ ! -f $(DESTDIR)$(CONFDIR)/goquotas.toml ]; then \
		install -m 640 configs/goquotas.example.toml $(DESTDIR)$(CONFDIR)/goquotas.toml; \
		echo "Installed starter config: $(DESTDIR)$(CONFDIR)/goquotas.toml — edit before use"; \
	else \
		echo "$(DESTDIR)$(CONFDIR)/goquotas.toml exists, skipping"; \
	fi

# Install systemd service files. Run 'sudo systemctl daemon-reload' afterwards.
# The service files assume binaries in /usr/local/bin and configs in
# /etc/powerscale-data-insights; edit them if you used a different PREFIX.
install-systemd:
	install -d $(DESTDIR)$(SYSTEMDDIR)
	install -m 644 systemd/pdi-gostats.service $(DESTDIR)$(SYSTEMDDIR)/pdi-gostats.service
	install -m 644 systemd/pdi-goppstats.service $(DESTDIR)$(SYSTEMDDIR)/pdi-goppstats.service
	install -m 644 systemd/pdi-goquotas.service $(DESTDIR)$(SYSTEMDDIR)/pdi-goquotas.service
	@echo ""
	@echo "Service files installed. To activate:"
	@echo "  sudo systemctl daemon-reload"
	@echo "  sudo useradd -r -s /usr/sbin/nologin pdi"
	@echo "  sudo mkdir -p /var/log/powerscale-data-insights"
	@echo "  sudo chown pdi:pdi /var/log/powerscale-data-insights"
	@echo "  sudo systemctl enable --now pdi-gostats pdi-goppstats pdi-goquotas"

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/gostats
	rm -f $(DESTDIR)$(BINDIR)/goppstats
	rm -f $(DESTDIR)$(BINDIR)/goquotas
	rm -f $(DESTDIR)$(BINDIR)/dashgen
