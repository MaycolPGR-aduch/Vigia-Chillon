FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# La base analítica y el modelo se construyen fuera del contenedor y viajan con él:
# el despliegue no necesita el Excel de origen ni volver a entrenar.
COPY datos/vigia.db datos/vigia.db
COPY modelo/artefactos modelo/artefactos
COPY api api
COPY modelo/__init__.py modelo/__init__.py
COPY web web
COPY informe informe

EXPOSE 8000

# Comprobación de salud: el orquestador reinicia el servicio si la API deja de responder
HEALTHCHECK --interval=60s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8000') + '/api/salud').read()"

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
