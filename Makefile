ENV = llm-grader

.PHONY: setup

setup:
	conda create -n $(ENV) -c conda-forge python=3.11 tesseract -y
	conda run -n $(ENV) pip install -r requirements.txt
	conda run -n $(ENV) playwright install chromium
