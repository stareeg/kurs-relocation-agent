-- 0113_drop_drive_ingest_manifest — снос последнего хвоста Drive-ингеста.
-- Таблица заведена в 0034 под манифест синхронизации Google Drive; сама подсистема ингеста
-- удалена вместе с графом знаний, читателя у таблицы не осталось (core/repo/drive_ingest.py
-- удалён этой же волной чистки).
drop table if exists drive_ingest_manifest;
