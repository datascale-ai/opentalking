.PHONY: test lint build-web

test:
	pytest tests -v

lint:
	ruff check opentalking/core opentalking/events opentalking/avatar apps tests

build-web:
	cd apps/web && npm run build
