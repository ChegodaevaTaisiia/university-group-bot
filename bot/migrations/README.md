Миграции Alembic.

Создать новую после изменения моделей:

    alembic revision --autogenerate -m "что изменилось"

Применить (main.py делает это сам при старте):

    alembic upgrade head
