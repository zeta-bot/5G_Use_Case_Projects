.PHONY: bootstrap check run train docker-build docker-check

bootstrap:
	python3 scripts/bootstrap.py

check:
	python3 scripts/check_setup.py

run:
	python3 scripts/run_app.py

train:
	python3 scripts/train_model.py

docker-build:
	docker build -t gesture-voice-app:latest .

docker-check:
	docker compose run --rm gesture-app
