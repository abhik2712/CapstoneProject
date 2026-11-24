FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 copilot \
    && install -d -o copilot -g copilot /app/runtime

COPY --chown=copilot:copilot copilot ./copilot
COPY --chown=copilot:copilot retrieval ./retrieval
COPY --chown=copilot:copilot baseline ./baseline
COPY --chown=copilot:copilot streamlit_app.py ./

USER copilot
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "streamlit_app.py", "--server.headless=true", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]
