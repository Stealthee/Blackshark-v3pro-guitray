PREFIX ?= /usr/local
DESTDIR ?=
PYTHON ?= python3

.PHONY: all install uninstall clean

all:
	@echo "Targets:"
	@echo "  make install   — install package, command, .desktop, icon (system-wide)"
	@echo "  make uninstall — reverse the above"
	@echo "  PREFIX=~/.local make install   — user-local install"

install:
	$(PYTHON) -m pip install --root="$(DESTDIR)" --prefix="$(PREFIX)" .
	install -Dm644 data/lynapse.desktop "$(DESTDIR)$(PREFIX)/share/applications/lynapse.desktop"
	install -Dm644 data/lynapse.svg "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/lynapse.svg"
	@if [ -z "$(DESTDIR)" ] && command -v gtk-update-icon-cache >/dev/null 2>&1; then \
		gtk-update-icon-cache -f -t "$(PREFIX)/share/icons/hicolor" 2>/dev/null || true; \
	fi
	@if [ -z "$(DESTDIR)" ] && command -v update-desktop-database >/dev/null 2>&1; then \
		update-desktop-database -q "$(PREFIX)/share/applications" 2>/dev/null || true; \
	fi
	@echo ""
	@echo "Installed. Run 'lynapse' or launch from your application menu."
	@echo "If your user is not in the 'openrazer' group, add it: sudo usermod -aG openrazer \$$USER (then re-login)"

uninstall:
	$(PYTHON) -m pip uninstall -y lynapse || true
	rm -f "$(DESTDIR)$(PREFIX)/share/applications/lynapse.desktop"
	rm -f "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/lynapse.svg"

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
