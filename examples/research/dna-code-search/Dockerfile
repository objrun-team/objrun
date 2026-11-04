FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ make && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy scipy numba sympy ortools
RUN useradd --uid 1000 --create-home researcher
USER researcher
WORKDIR /work
