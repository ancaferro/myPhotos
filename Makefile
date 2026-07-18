PYTHON ?= python3
PID_FILE := .myphotos.pid
LOG_FILE := server.log
URL := http://127.0.0.1:5001

.DEFAULT_GOAL := start
.PHONY: start stop restart

start:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "myPhotos is already running (PID $$(cat $(PID_FILE))) — $(URL)"; \
	else \
		nohup $(PYTHON) app.py > $(LOG_FILE) 2>&1 & echo $$! > $(PID_FILE); \
		echo "myPhotos started on $(URL) (PID $$(cat $(PID_FILE)), log: $(LOG_FILE))"; \
	fi

stop:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		kill $$(cat $(PID_FILE)) && rm -f $(PID_FILE) && echo "myPhotos stopped"; \
	else \
		rm -f $(PID_FILE); echo "myPhotos is not running"; \
	fi

restart: stop start
