-- Маркер: scoring_importance пишется лениво при PATCH из UI «Резюме».
-- Пока ключа нет, GET /api/settings восстанавливает уровни 1-5 из scoring_weights
-- (round(weight/5)), чтобы кастомные проценты не отображались как дефолтная шкала.

SELECT 1;
