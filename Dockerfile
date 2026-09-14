FROM python:3.12-slim
RUN pip install --no-cache-dir mitmproxy
WORKDIR /addons
EXPOSE 8080
ENTRYPOINT ["mitmdump"]
