.PHONY: init models build run run-live run-headless

init:
	git submodule update --init --recursive

models:
	./scripts/download-models.sh

build:
	docker build --network host -t digital-clone:local .

run:
	./scripts/run-docker.sh --mode offline --style cinematic

run-live:
	./scripts/run-docker.sh --mode live

run-headless:
	docker compose run --rm digital-clone
