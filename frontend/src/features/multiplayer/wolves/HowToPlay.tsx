/**
 * Короткий «Как играть» на хабе — один экран, без простыни (Э15).
 */
export function HowToPlay() {
  return (
    <section
      className="w-full rounded-md border border-slate-200 bg-slate-50/70 px-4 py-3"
      aria-labelledby="mp-how-to-play"
    >
      <h2 id="mp-how-to-play" className="mp-display text-sm font-semibold text-slate-900">
        Как играть
      </h2>
      <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-slate-700">
        <li>
          Создай стол или нажми «Войти» в чужой. Никнейм — как тебя зовут за столом.
        </li>
        <li>
          Создатель — <strong className="font-semibold">хрюша</strong>: смотрит бумаги,
          отмечает улики, ставит штампы (на собес / отказ / оффер).
        </li>
        <li>
          Остальные — <strong className="font-semibold">кандидаты</strong>: кладут карты
          опыта и отвечают на короткий вопрос. Свободные места играют боты.
        </li>
        <li>
          Среди кандидатов спрятаны <strong className="font-semibold">волки</strong>. Задача
          хрюши — не дать им оффер; волкам — проскочить или дожить до конца.
        </li>
        <li>
          Партия на несколько слотов → раскрытие ролей. «Ещё раунд» или новый стол — всегда
          новый расклад карт и ролей.
        </li>
      </ol>
    </section>
  )
}
