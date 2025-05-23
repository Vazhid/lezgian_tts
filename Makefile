.PHONY: setup shell test clean

setup:
	poetry install

shell:
	poetry env activate

test:
	poetry run pytest

run:
	poetry run python app.py

clean:
	poetry cache clear --all -n