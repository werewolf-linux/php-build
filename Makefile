PYTHON ?= python3
ARCH ?= $(shell uname -m)
MELANGE ?= $(if $(wildcard build/tools/melange),$(abspath build/tools/melange),melange)
export MELANGE

.PHONY: refresh test verify derive prepare build check
refresh:
	$(PYTHON) scripts/refresh.py $(if $(WOLFI),--wolfi $(WOLFI))

build/inputs/upstream.lock.json:
	$(PYTHON) scripts/refresh.py $(if $(WOLFI),--wolfi $(WOLFI))

# The unit tests need no network and no captured inputs.
test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

verify: build/inputs/upstream.lock.json
	$(PYTHON) scripts/verify.py

derive: verify
	$(PYTHON) scripts/derive.py

prepare: verify
	$(PYTHON) scripts/prepare.py build/source

build: derive
	$(PYTHON) scripts/signing-key.py
	$(PYTHON) scripts/build.py --arch $(ARCH)

check: test verify
