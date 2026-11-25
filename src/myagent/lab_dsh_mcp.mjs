// Authored adapter for the experiment subject's public plugin interface.
// MCP wire protocol and tool mapping are ours; no DSH implementation copied.
export const name = 'myagent-labstats-mcp';
export const inject = ['tools'];

export async function apply(ctx) {
  const endpoint = process.env.MYAGENT_MCP_ENDPOINT;
  let serial = 0;
  async function rpc(method, params = {}) {
    const body = { jsonrpc: '2.0', method, params };
    if (!method.startsWith('notifications/')) body.id = ++serial;
    const response = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(35000),
    });
    if (response.status === 202) return {};
    const message = await response.json();
    if (message.error) throw Error(message.error.message);
    return message.result;
  }
  await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'myagent-dsh-study', version: '1' } });
  await rpc('notifications/initialized');
  const { tools } = await rpc('tools/list');
  for (const tool of tools) {
    ctx.tools.register({
      name: `mcp__labstats__${tool.name}`,
      description: tool.description,
      parameters: tool.inputSchema,
      output: { schema: { type: 'object', additionalProperties: true }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      execute: args => rpc('tools/call', { name: tool.name, arguments: args }),
    });
  }
}
