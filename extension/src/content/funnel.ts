/** Статусы воронки — синхрон с core/kernel/schemas/funnel.py.
 *  ARCHIVE оставлен как алиас чтения легаси; новые записи пишем в REJECTED. */
const FUNNEL_STATUS = {
  VIEWED: 'Просмотр',
  APPLIED: 'Отклик',
  REJECTED: 'Отказ',
  SCREENING: 'Скрининг',
  TECH: 'Техничка',
  FINAL: 'Финал',
  OFFER: 'Оффер',
  ARCHIVE: 'Архив',
};

/** CSS-класс для бейджа статуса в панели. */
const FUNNEL_STATUS_CLASS = {
  [FUNNEL_STATUS.VIEWED]: 'viewed',
  [FUNNEL_STATUS.APPLIED]: 'applied',
  [FUNNEL_STATUS.REJECTED]: 'rejected',
  [FUNNEL_STATUS.SCREENING]: 'screening',
  [FUNNEL_STATUS.TECH]: 'tech',
  [FUNNEL_STATUS.FINAL]: 'final',
  [FUNNEL_STATUS.OFFER]: 'offer',
  [FUNNEL_STATUS.ARCHIVE]: 'rejected',
};

function funnelStatusClass(status) {
  if (!status) return 'unknown';
  if (status === FUNNEL_STATUS.ARCHIVE) return 'rejected';
  return FUNNEL_STATUS_CLASS[status] || 'unknown';
}

function funnelStatusLabel(status) {
  if (!status) return 'Статус не задан';
  if (status === FUNNEL_STATUS.ARCHIVE) return FUNNEL_STATUS.REJECTED;
  return status;
}

export {
  FUNNEL_STATUS,
  funnelStatusClass,
  funnelStatusLabel,
}
