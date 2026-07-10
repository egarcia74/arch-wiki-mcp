.PHONY: help test audit fixtures serve

PAGES ?=

help:
	@echo "test      Offline test suite. No network: sockets are blocked by conftest."
	@echo "audit     Check the extractor's invariants against the LIVE wiki."
	@echo "          make audit PAGES=\"Btrfs LVM\"   (default: a 36-page corpus)"
	@echo "fixtures  Re-record test fixtures from the live wiki. Moves pinned hashes."
	@echo "serve     Run the MCP server on stdio."

test:
	python3 -m pytest -ra --cov --cov-report=term-missing

# Deliberately outside pytest: it talks to the network, and the suite blocks
# sockets on purpose. Three defects shipped past a green suite and were caught
# here on first contact with real content.
audit:
	python3 scripts/live_audit.py $(PAGES)

fixtures:
	python3 tests/record_fixtures.py

serve:
	python3 src/mcp_server.py
