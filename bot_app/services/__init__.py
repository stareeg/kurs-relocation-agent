"""Сервисы бота после R-35: только форматтеры и TG-клей.

Доменная логика — в ``core.domains.*`` / ``core.platform.llm``.
Оставшееся здесь:
- форматтеры: ``vacancy_card``, ``batch_summary``
- PNG-карточка: ``card_image``
- отправка карточки: ``card_replace`` (/ TB-5.4: PNG|текст по prefs)
- уборка батча: ``batch_cleanup``
- UI: ``menu_manager`` (адаптивное меню)
- пуш из веба: ``push_handler`` (очередь ``tg_push``)
- доставка «аккаунту N» / рассылка активным: ``notify`` (M8, plans/
  multitenancy_gaps_2026_08_06.md §5.5 — заведён, но пока никем не вызывается: дайджест и
  discovery-прогрев product-но выключены, см. докстринг ``scheduler``)
- TG-клей: ``forward_batcher``, ``scheduler``, ``salary_calib_orchestrator``,
  ``prep_scheduler``, тонкий ``salary_calib_pipeline`` (подсказки BotSettings)

``digest``/``warmup_summary``/``discovery`` удалены (M0-M7, 2026-08-06) вместе с
дайджестом/discovery-прогревом — ai-slop, основной поток вакансий закрывают расширение и
пересылка.
"""
