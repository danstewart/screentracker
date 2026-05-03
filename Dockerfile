# syntax = docker/dockerfile:1.2

FROM python:3.14-slim-bookworm

ENV FLASK_APP="${FLASK_APP}" \
    FLASK_DEBUG="${FLASK_DEBUG}" \
    PYTHONFAULTHANDLER=1

RUN rm /etc/apt/apt.conf.d/docker-clean

ENV DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt,id=apt \
    apt-get update \
    && apt-get -y upgrade \
    && apt-get install -y --no-install-recommends \
    curl sqlite3

RUN useradd --create-home app
USER app
WORKDIR /home/app/screentracker
RUN mkdir -p /home/app/screentracker/db

ENV PATH="/home/app/.local/bin/:${PATH}"

COPY --chown=app requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=app:app . ./

EXPOSE 1234

CMD ["python", "app.py"]
