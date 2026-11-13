# Package the grading service and corpus together. **The oracle stays inside this image.**
#
#   docker build -t tgengin-cmt-grader examples/benchmark/cmt
#   docker run --rm -p 127.0.0.1:7901:7901 tgengin-cmt-grader
#
# The engine needs no changes: it only knows `http://127.0.0.1:7901/{parsed,equiv}` and does not care whether a WSL venv or a container serves them.
#
# Building requires network access: fetch the corpus from HuggingFace and the official grader from GitHub, **pinning both versions**. Grader drift makes scores incomparable with the paper's table.
FROM python:3.12-slim

# Pin the official grader to this commit, also used by the WSL-venv path in setup.sh.
ARG HARNESS_REF=c114183
ARG HARNESS_URL=https://github.com/JamesRoggeveen/cmt_benchmark_data/archive
ARG DATA_URL=https://huggingface.co/datasets/JVRoggeveen/cmt_benchmark/resolve/main/cmt_data.jsonl

# Convert `ARG` to `ENV` for the value read by `RUN`; the image also records the version from which it was built.
ENV TGENGIN_CMT_HOME=/oracle \
    TGENGIN_CMT_PORT=7901 \
    PYTHONUNBUFFERED=1 \
    HARNESS_REF=${HARNESS_REF} \
    HARNESS_URL=${HARNESS_URL} \
    DATA_URL=${DATA_URL}

# **Install no apt packages.** Python's urllib and tarfile suffice to download two files. Installing git/curl uses plain HTTP to deb.debian.org, which produced 502 errors behind the proxy in practice. They would also remain in this answer-bearing image, where fewer tools are preferable.
#
# Install only the three grading dependencies. Official pyproject also lists openai/anthropic/google-genai/datasets/matplotlib for model runs and plotting. Copy the official dependency pins.
RUN pip install --no-cache-dir "sympy==1.13.3" "numpy==2.2.5" "regex==2024.11.6"

WORKDIR /oracle
RUN <<'PY' python
import io, os, tarfile, urllib.request, pathlib

ref, base, data = os.environ["HARNESS_REF"], os.environ["HARNESS_URL"], os.environ["DATA_URL"]

def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()

# Download the official grader as a tarball rather than using git; this also keeps .git out of the image.
raw = get(f"{base}/{ref}.tar.gz")
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
    root = tf.getnames()[0].split("/")[0]
    tf.extractall("/oracle/vendor", filter="data")
os.rename(f"/oracle/vendor/{root}", "/oracle/vendor/cmt_benchmark_data")
assert pathlib.Path("/oracle/vendor/cmt_benchmark_data/src/cmtbench/evaluator.py").exists(), "Official grader was not extracted"
print(f"Extracted grader {ref}")

# Problem corpus.
book = get(data)
pathlib.Path("/oracle/cmt_data.jsonl").write_bytes(book)
n = sum(1 for line in book.splitlines() if line.strip())
assert n == 50, f"Expected 50 dataset rows; got {n}"
print(f"Dataset: {n} rows")
PY

# Keep grader.py in its own layer, so edits do not redownload the corpus and official grader.
COPY grader.py /app/grader.py
WORKDIR /app

# Validate the grader during the build: feeding back corpus GT must yield 5/5 equivalent answers under the official criterion.
# An invalid installation fails here, before the benchmark run.
RUN python grader.py --selftest

# The grading service needs neither file writes nor root privileges.
RUN useradd -u 10001 -m grader && chown -R grader /oracle /app
USER grader

EXPOSE 7901
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7901/health',timeout=2).status==200 else 1)"

CMD ["python", "grader.py"]
