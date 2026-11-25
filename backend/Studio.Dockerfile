FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends pandoc fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt requirements-studio.txt ./
RUN pip install --no-cache-dir -r requirements-studio.txt
COPY app app
RUN useradd --create-home studio && mkdir /srv/state && chown studio:studio /srv/state
USER studio
ENV STUDIO_DATA_DIR=/srv/state
CMD ["uvicorn","app.studio.server:app","--host","0.0.0.0","--port","8129","--workers","1","--no-access-log"]
