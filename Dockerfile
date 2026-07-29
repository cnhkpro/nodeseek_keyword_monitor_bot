FROM python:3.10-slim

# 设置时区为上海（解决容器内时间与本地不符的问题）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 启动命令
CMD ["python", "ns_bot_multi.py"]