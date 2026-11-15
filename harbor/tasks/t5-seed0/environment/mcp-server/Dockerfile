FROM python:3.12-slim
WORKDIR /srv
COPY pharmacy_env /srv/pharmacy_env
EXPOSE 8000
CMD ["python", "-m", "pharmacy_env.mcp_server", "--task", "T5", "--seed", "0", "--http", "8000", "--out", "/tmp/trajectory.jsonl"]
