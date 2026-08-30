# A throwaway Python sandbox for the solver.
#
#   docker build -t tgengin-sandbox -f examples/benchmark/cmt/sandbox.Dockerfile examples/benchmark/cmt
#
# **This is not the grader image.** It carries no problem set and no grading code:
# the solver runs here, the answers live over there, and the two never share a
# filesystem. Keeping them in one image would put the solver next to the oracle.
#
# The old repo gave its agent exactly two tools: a submit tool and `python_exec`.
# Ours had `bash` instead - on a box with no working Python, which is how a task
# once burned twelve execution units on `python --version` without writing a
# single character of an answer.
FROM python:3.12-slim

# Same pins as the grader, so a number computed here and a number checked there
# come from the same library versions.
RUN pip install --no-cache-dir "sympy==1.13.3" "numpy==2.2.5" "scipy==1.15.2"

# Nothing is written here; the runner mounts nothing and passes code on stdin.
RUN useradd -u 10002 -m runner
USER runner
WORKDIR /tmp

CMD ["python", "-c", "print('sandbox ready')"]
