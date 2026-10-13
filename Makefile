PYTHON_VERSION ?= 3.15
# Keep in sync with the Python matrix in .github/workflows/test.yml.
PYTHON_VERSIONS := 3.10 3.11 3.12 3.13 3.14 3.15
TEST_ARGS ?=

.PHONY: test test-matrix

test:
	docker build -f Dockerfile.test --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -t boilerio-test:$(PYTHON_VERSION) .
	docker run --rm boilerio-test:$(PYTHON_VERSION) $(TEST_ARGS)

test-matrix:
	@status=0; \
	for version in $(PYTHON_VERSIONS); do \
		echo "Testing Python $$version"; \
		$(MAKE) test PYTHON_VERSION=$$version || status=1; \
	done; \
	exit $$status
