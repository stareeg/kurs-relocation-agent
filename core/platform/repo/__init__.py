"""Repository-слой инфраструктуры: async-функции get/save/list → Pydantic, без доменных импортов.

Конвенция (В2.2): SQL рядом с функцией, без квери-билдеров/ORM. Каждая функция
принимает `db` (pool или connection) — по умолчанию глобальный пул из core.platform.db.pool.
"""
