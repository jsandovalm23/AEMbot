# Usa Python 3.10.13 para evitar el error de 'audioop'
FROM python:3.10.13-slim

# Configuración básica de Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Crea directorio de trabajo
WORKDIR /app

# Instala dependencias del sistema (opcionales, pero útiles)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copia requirements e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código
COPY . .

# Asegura el directorio de datos
RUN mkdir -p /app/data

# Expone el puerto (Render asigna $PORT; tu server.py lo usará)
EXPOSE 10000

# Usa tini como init (manejo de señales correcto)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Arranca el bot y el servidor de salud en paralelo
# - src.main: tu bot
# - server.py: servidor HTTP con /healthz
CMD ["bash", "-lc", "python -m src.main & python server.py"]
