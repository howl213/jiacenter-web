FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# 컨테이너 안에서는 0.0.0.0 으로 열지만, 바깥(호스트)에는 docker-compose.yml 이 127.0.0.1 로만 연다.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_dummy && python manage.py runserver 0.0.0.0:8000"]
