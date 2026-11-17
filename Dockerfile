FROM python:3.11-slim

WORKDIR /app

# 只拷运行所需文件（大文件见 .dockerignore）
COPY . .

# 中文文件名在 URL 里要转义，容器内额外生成一份 index.html 更方便
RUN cp "$(ls -1 *.html | head -n 1)" index.html

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# 每 10 分钟自动刷新；首次启动若无 data.json 会先抓一次
CMD ["python", "serve.py", "--port", "8080", "--interval", "600"]
