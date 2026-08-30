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
ARG DATA_URL=https://huggingface.co/datasets/JVRoggeveen/cmt_benchmark/resolve/main/cmt_data.jsonl

ENV TGENGIN_CMT_HOME=/oracle \
    TGENGIN_CMT_PORT=7901 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# **只装判卷那条路要的三个。** 官方 pyproject 还列着 openai / anthropic /
# google-genai / datasets / matplotlib —— 那是它「拿模型跑一遍」和「画图」那半边要的。
# 版本照抄官方 pin。
RUN pip install --no-cache-dir "sympy==1.13.3" "numpy==2.2.5" "regex==2024.11.6"

WORKDIR /oracle
RUN mkdir -p /oracle/vendor \
 && git clone --no-checkout https://github.com/JamesRoggeveen/cmt_benchmark_data \
      /oracle/vendor/cmt_benchmark_data \
 && git -C /oracle/vendor/cmt_benchmark_data checkout "$HARNESS_REF" \
 && rm -rf /oracle/vendor/cmt_benchmark_data/.git \
 && curl -sSL -o /oracle/cmt_data.jsonl "$DATA_URL" \
 && wc -l < /oracle/cmt_data.jsonl

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
