.PHONY: test install dmg clean

test:
	python3 -m unittest discover -s tests -v
	./tests/integration.sh

install:
	./scripts/install.sh

dmg:
	./scripts/build_dmg.sh

clean:
	python3 -c 'import shutil; shutil.rmtree("build", ignore_errors=True)'
