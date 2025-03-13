FROM python:3.12-alpine

WORKDIR /app

RUN adduser --system nonroot -u 1000 -g 1000 && \
    chown -R 1000:1000 /app
USER nonroot

COPY requirements.txt /tmp/requirements.txt

RUN pip install -r /tmp/requirements.txt

COPY main.py /app/main.py

EXPOSE 8000

CMD [ "python", "main.py" ]
