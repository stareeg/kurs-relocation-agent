import assert from 'node:assert/strict';
import {
  convMessagesToQaHistory,
  qaHistoryForAsk,
  QA_HISTORY_LIMIT,
} from '../src/content/qa-conversation.ts';

{
  const history = convMessagesToQaHistory([
    { kind: 'hr_in', body: 'Здравствуйте' },
    { kind: 'llm_user', body: 'Какой стек?' },
    { kind: 'llm_assistant', body: 'React и TypeScript' },
    { kind: 'hr_out', body: 'Спасибо' },
    { kind: 'llm_user', body: '  ' },
  ]);
  assert.deepEqual(history, [
    { role: 'user', content: 'Какой стек?' },
    { role: 'assistant', content: 'React и TypeScript' },
  ]);
}

{
  const long = Array.from({ length: QA_HISTORY_LIMIT + 3 }, (_, i) => ({
    role: i % 2 === 0 ? ('user' as const) : ('assistant' as const),
    content: String(i),
  }));
  const sliced = qaHistoryForAsk(long);
  assert.equal(sliced.length, QA_HISTORY_LIMIT);
  assert.equal(sliced[0]?.content, '3');
  assert.equal(sliced.at(-1)?.content, String(QA_HISTORY_LIMIT + 2));
}

console.log('qa-conversation.test.ts: ok');
