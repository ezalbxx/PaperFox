// Original study driver using the installed subject's public services.
// DSH remains an external experiment dependency; its implementation is not copied.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';

export const name = 'myagent-study-interview';
export const inject = ['agents', 'sessions', 'agentDefaultModel', 'sessionPersistence'];

function save(path, value) {
  writeFileSync(path + '.next', JSON.stringify(value, null, 2), 'utf8');
  renameSync(path + '.next', path);
}

export function apply(ctx) {
  const exit = ctx.get('appExit');
  const packet = JSON.parse(readFileSync(process.env.MYAGENT_INTERVIEW_PACKET, 'utf8'));
  const requireSubject = createRequire(pathToFileURL(process.env.MYAGENT_DSH_ENTRY));
  const load = name => import(pathToFileURL(requireSubject.resolve(name)).href);
  async function conduct() {
    const [{ createUserMessage }, { installModelSelection }] = await Promise.all([
      load('@deepseek-ai/dsh-llm'), load('@deepseek-ai/dsh-agent'),
    ]);
    await ctx.get('loader')?.await();
    const selection = ctx.agentDefaultModel.currentSelection();
    const options = {
      agentOptions: { provider: selection.provider, model: selection.model },
      setup: scope => { installModelSelection(scope, { current: selection, assembled: undefined }); },
    };
    const handle = packet.resume
      ? await ctx.agents.resume({ ...options, resumeSessionId: packet.session_id })
      : await ctx.agents.create({ ...options, sessionId: packet.session_id, meta: { cwd: process.cwd() } });
    const agent = handle.agent;
    await agent.whenIdle();
    const progress = { session_id: packet.session_id, completed: [], status: 'running' };
    // Find completed user turns in the real event log, also covering a crash
    // between the subject's flush and our progress-file update.
    const turns = [];
    let current = null;
    for (const event of agent.session.events) {
      if (event.type === 'turn/start') current = { seq: event.seq, text: '' };
      if (current && event.type === 'assistant/message') {
        current.text = event.data.message.content.filter(x => x.type === 'text').map(x => x.text).join('');
      }
      if (current && event.type === 'turn/end') {
        current.reason = event.data.reason;
        turns.push(current); current = null;
      }
    }
    for (let i = 0; i < packet.prompts.length; i++) {
      if (i < turns.length) {
        if (turns[i].reason?.kind !== 'completed') throw Error('Previous turn did not complete; inspect original session before retrying.');
        progress.completed.push({ index: i, prompt: packet.prompts[i], ...turns[i], reused: true });
        continue;
      }
      const first = agent.session.seq;
      agent.followup(createUserMessage({ content: [{ type: 'text', text: packet.prompts[i] }], source: { kind: 'user' } }));
      await agent.whenIdle();
      await ctx.sessions.flush(agent.session);
      const interval = agent.session.events.filter(e => e.seq >= first);
      const messages = interval.filter(e => e.type === 'assistant/message');
      const ending = interval.filter(e => e.type === 'turn/end').at(-1);
      const answer = messages.at(-1)?.data.message.content.filter(x => x.type === 'text').map(x => x.text).join('') || '';
      progress.completed.push({ index: i, prompt: packet.prompts[i], text: answer, seq: first, reason: ending?.data.reason });
      save(packet.progress_path, progress);
      process.stdout.write(JSON.stringify(progress.completed.at(-1)) + '\n');
      if (ending?.data.reason?.kind !== 'completed') throw Error('Study turn failed; original events retained.');
    }
    progress.status = 'completed'; save(packet.progress_path, progress);
    await ctx.sessions.flush(agent.session);
    exit(0);
  }
  conduct().catch(error => { process.stderr.write(String(error.stack || error) + '\n'); exit(1); });
}
