/** U-16: актуальная подсказка при сетевой ошибке скоринга. */
export function normalizeScoreErrorMessage(message: unknown): string {
  const msg = String(message || 'Неизвестная ошибка');
  if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
    return 'Backend недоступен. Проверьте, что сервис запущен.';
  }
  return msg;
}
