.PHONY: install api ui eval eval-llm test clean

install:
	pip install -r requirements.txt
	cd frontend && npm install

api:
	cd backend && uvicorn app.main:app --reload --port 8000

ui:
	cd frontend && npm run dev

eval:
	python evals/run_eval.py

eval-llm:
	python evals/run_eval.py --llm --compare -v

test:
	pytest -q

clean:
	rm -f data/aliases.db
	find . -name __pycache__ -type d -exec rm -rf {} +
