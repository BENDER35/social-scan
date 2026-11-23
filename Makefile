.PHONY: test selftest zip deb release clean

test:
	python3 -m unittest discover -s tests -v

selftest:
	python3 -m social_scan --self-test

zip:
	bash scripts/build_release.sh zip

deb:
	bash scripts/build_release.sh deb

release:
	bash scripts/build_release.sh all

clean:
	rm -rf dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
