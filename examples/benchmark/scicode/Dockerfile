FROM python:3.12.11-slim-bookworm
RUN pip install --no-cache-dir numpy==1.26.4 scipy==1.14.1 pandas==2.2.3 h5py==3.12.1 sympy==1.13.3 matplotlib==3.9.3 datasets==3.2.0 regex==2024.11.6
ENV MPLCONFIGDIR=/tmp/matplotlib PYTHONDONTWRITEBYTECODE=1
WORKDIR /tmp
USER 65534:65534
