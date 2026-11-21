FROM python:3.11-slim-bookworm

WORKDIR /app
COPY bridge.py .
USER 65534:65534
EXPOSE 18774
ENTRYPOINT ["python", "-u", "bridge.py", "--data-dir", "/data", "--artwork-dir", "/artwork"]
CMD ["--listen", "0.0.0.0"]
