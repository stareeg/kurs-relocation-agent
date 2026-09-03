"""AppSettings — продуктовые пути и ручки из .env (не путать с таблицей app_settings).

Пользовательские веса/ключ OpenRouter с вкладки «Параметры» живут в Postgres
(`core.platform.repo.settings` / таблица `app_settings`) и перекрывают .env в рантайме.
"""

from __future__ import annotations

from pydantic import BaseModel


class AppSettings(BaseModel):
    """Пути артефактов, логи, скоринг-флаги уровня процесса."""

    # --- Логирование ---
    log_level: str = "INFO"
    log_level_file: str = "DEBUG"
    log_dir: str = "logs"
    log_rich: bool = True
    log_rotation_mb: int = 5
    log_backups: int = 5

    # --- Резюме / скоринг ---
    # Канон резюме — JSON; скоринг рендерит markdown в рантайме.
    resume_data_path: str = "resume/resume_data.json"
    scoring_salary_use_llm: bool = True
    # Опциональный JSON-сид рыночных бенчмарков; пусто — не загружать.
    salary_benchmarks_path: str = ""
    resume_strengthen_top_vacancies: int = 5
    resume_ats_fit_top_vacancies: int = 5
    search_horizon_days: int = 60

    # --- Вложения-картинки в чатах ---
    # Через сколько часов удалять несвязанные вложения (загрузил в композер и передумал отправлять).
    attachment_gc_after_hours: int = 24


__all__ = ["AppSettings"]
