# 判卷台连题库一起打包。**oracle 不出这个镜像。**
#
#   docker build -t tgengin-cmt-grader examples/benchmark/cmt
#   docker run --rm -p 127.0.0.1:7901:7901 tgengin-cmt-grader
#
# 引擎那边一个字不用改 —— 它只认 `http://127.0.0.1:7901/{parsed,equiv}` 这两个名字，
# 后面是 WSL 里的一个 venv 还是一个容器，跟它无关。
#
# 构建要联网：题库从 HuggingFace 拉，官方判据从 GitHub 拉，**两样都钉死版本**
# —— 判据版本一飘，分数跟论文那张表就不可比了。
FROM python:3.12-slim

# 官方判据钉在这个 commit。setup.sh 那条路（WSL venv）拉的也是它。
ARG HARNESS_REF=c114183
ARG HARNESS_URL=https://github.com/JamesRoggeveen/cmt_benchmark_data/archive
ARG DATA_URL=https://huggingface.co/datasets/JVRoggeveen/cmt_benchmark/resolve/main/cmt_data.jsonl

# `ARG` 在 `RUN` 里读不到，得转成 `ENV` —— 顺带镜像自己也就记下了它是从哪个版本建的。
ENV TGENGIN_CMT_HOME=/oracle \
    TGENGIN_CMT_PORT=7901 \
    PYTHONUNBUFFERED=1 \
    HARNESS_REF=${HARNESS_REF} \
    HARNESS_URL=${HARNESS_URL} \
    DATA_URL=${DATA_URL}

# **不装 apt 包。** 拉两个文件而已，python 自带 urllib 和 tarfile 就够了 ——
# 装 git/curl 要走 deb.debian.org 的明文 HTTP，在代理后面容易 502（实测卡在这儿），
# 而且它们会留在镜像里：这是个放着答案的容器，能少一样是一样。
#
# 只装判卷那条路要的三个。官方 pyproject 还列着 openai / anthropic / google-genai /
# datasets / matplotlib —— 那是它「拿模型跑一遍」和「画图」那半边要的。版本照抄官方 pin。
RUN pip install --no-cache-dir "sympy==1.13.3" "numpy==2.2.5" "regex==2024.11.6"

WORKDIR /oracle
RUN <<'PY' python
import io, os, tarfile, urllib.request, pathlib

ref, base, data = os.environ["HARNESS_REF"], os.environ["HARNESS_URL"], os.environ["DATA_URL"]

def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()

# 官方判据：拿 tarball，不用 git —— 顺带也就没有 .git 留在镜像里。
raw = get(f"{base}/{ref}.tar.gz")
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
    root = tf.getnames()[0].split("/")[0]
    tf.extractall("/oracle/vendor", filter="data")
os.rename(f"/oracle/vendor/{root}", "/oracle/vendor/cmt_benchmark_data")
assert pathlib.Path("/oracle/vendor/cmt_benchmark_data/src/cmtbench/evaluator.py").exists(), "官方判据没解出来"
print(f"判据 {ref} 解好了")

# 题库
book = get(data)
pathlib.Path("/oracle/cmt_data.jsonl").write_bytes(book)
n = sum(1 for line in book.splitlines() if line.strip())
assert n == 50, f"题库该是 50 行，拿到 {n} 行"
print(f"题库 {n} 行")
PY

# grader.py 单独一层：改它不用重拉题库和判据。
COPY grader.py /app/grader.py
WORKDIR /app

# 构建时就把判据验一遍：拿题库自己的 GT 当回答喂回去，官方判据该说 5/5 等价。
# 装错了在这儿就炸，不会等到跑 bench 才发现。
RUN python grader.py --selftest

# 判卷台不需要写任何东西，也不需要 root。
RUN useradd -u 10001 -m grader && chown -R grader /oracle /app
USER grader

EXPOSE 7901
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7901/health',timeout=2).status==200 else 1)"

CMD ["python", "grader.py"]
