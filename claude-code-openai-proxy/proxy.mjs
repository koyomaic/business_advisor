// Anthropic Messages API -> OpenAI Chat Completions translation proxy.
// Lets Claude Code talk to any OpenAI-compatible backend (e.g. opencode's default model).
// Zero dependencies. Node >= 18 (uses global fetch).
import http from 'node:http';
import fs from 'node:fs';

// Config precedence: environment variables > config.json > defaults.
const configPath = new URL('./config.json', import.meta.url);
const fileConfig = fs.existsSync(configPath)
  ? JSON.parse(fs.readFileSync(configPath, 'utf8'))
  : {};

const host = process.env.PROXY_HOST || fileConfig.host || '127.0.0.1';
const port = Number(process.env.PROXY_PORT || fileConfig.port || 8790);
const baseURL = process.env.UPSTREAM_BASE_URL || fileConfig.baseURL;
const apiKey = process.env.UPSTREAM_API_KEY || fileConfig.apiKey;
const model = process.env.UPSTREAM_MODEL || fileConfig.model;

if (!baseURL || !apiKey || !model) {
  console.error(
    'Missing config. Provide config.json (see config.example.json) or set ' +
      'UPSTREAM_BASE_URL, UPSTREAM_API_KEY, UPSTREAM_MODEL env vars.'
  );
  process.exit(1);
}

const UPSTREAM = baseURL.replace(/\/$/, '') + '/chat/completions';

const log = (...a) => console.log(new Date().toISOString(), ...a);

const STOP_MAP = {
  stop: 'end_turn',
  length: 'max_tokens',
  tool_calls: 'tool_use',
  function_call: 'tool_use',
  content_filter: 'end_turn',
};

// ---------- Anthropic request -> OpenAI request ----------
function toOpenAI(body) {
  const out = { model, stream: !!body.stream };
  out.max_tokens = body.max_tokens ?? 1024;
  if (body.temperature != null) out.temperature = body.temperature;
  if (body.top_p != null) out.top_p = body.top_p;
  if (Array.isArray(body.stop_sequences) && body.stop_sequences.length)
    out.stop = body.stop_sequences;

  const messages = [];
  const systemTexts = [];

  const blocksToText = (content) => {
    if (typeof content === 'string') return content;
    if (Array.isArray(content))
      return content
        .map((b) => (b && typeof b.text === 'string' ? b.text : ''))
        .join('\n');
    return content == null ? '' : JSON.stringify(content);
  };

  if (body.system) {
    const text = blocksToText(body.system);
    if (text.trim()) systemTexts.push(text);
  }

  for (const m of body.messages || []) {
    const role = m.role;

    // Claude Code's SDK injects extra system messages mid-conversation, but the
    // upstream requires all system content at the beginning -> merge it up front.
    if (role === 'system') {
      const text = blocksToText(m.content);
      if (text.trim()) systemTexts.push(text);
      continue;
    }

    if (typeof m.content === 'string') {
      messages.push({ role, content: m.content });
      continue;
    }

    const blocks = Array.isArray(m.content) ? m.content : [];

    if (role === 'assistant') {
      let text = '';
      const tool_calls = [];
      for (const b of blocks) {
        if (b.type === 'text') text += b.text ?? '';
        else if (b.type === 'tool_use')
          tool_calls.push({
            id: b.id,
            type: 'function',
            function: { name: b.name, arguments: JSON.stringify(b.input ?? {}) },
          });
      }
      const msg = { role: 'assistant', content: text || null };
      if (tool_calls.length) msg.tool_calls = tool_calls;
      messages.push(msg);
    } else if (role === 'user') {
      let text = '';
      const parts = [];
      for (const b of blocks) {
        if (b.type === 'text') {
          text += b.text ?? '';
        } else if (b.type === 'tool_result') {
          let c = b.content;
          if (Array.isArray(c))
            c = c
              .map((x) =>
                x.type === 'text' ? x.text : x.type === 'image' ? '[image]' : ''
              )
              .join('');
          messages.push({
            role: 'tool',
            tool_call_id: b.tool_use_id,
            content: typeof c === 'string' ? c : JSON.stringify(c ?? ''),
          });
        } else if (b.type === 'image') {
          const src = b.source || {};
          if (src.type === 'base64')
            parts.push({
              type: 'image_url',
              image_url: { url: `data:${src.media_type};base64,${src.data}` },
            });
          else if (src.type === 'url')
            parts.push({ type: 'image_url', image_url: { url: src.url } });
        }
      }
      if (parts.length) {
        if (text) parts.unshift({ type: 'text', text });
        messages.push({ role: 'user', content: parts });
      } else if (text) {
        messages.push({ role: 'user', content: text });
      }
    } else {
      messages.push({
        role,
        content:
          typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
      });
    }
  }

  if (systemTexts.length)
    messages.unshift({ role: 'system', content: systemTexts.join('\n\n') });

  out.messages = messages;

  if (Array.isArray(body.tools) && body.tools.length) {
    out.tools = body.tools.map((t) => ({
      type: 'function',
      function: {
        name: t.name,
        description: t.description || '',
        parameters: t.input_schema || { type: 'object', properties: {} },
      },
    }));
    const tc = body.tool_choice;
    if (tc) {
      if (tc.type === 'auto') out.tool_choice = 'auto';
      else if (tc.type === 'any') out.tool_choice = 'required';
      else if (tc.type === 'none') out.tool_choice = 'none';
      else if (tc.type === 'tool')
        out.tool_choice = { type: 'function', function: { name: tc.name } };
    }
  }

  return out;
}

// ---------- OpenAI response -> Anthropic response (non-streaming) ----------
function fromOpenAI(json, reqModel) {
  const choice = json.choices?.[0] || {};
  const msg = choice.message || {};
  const content = [];
  if (msg.content) content.push({ type: 'text', text: msg.content });
  for (const tc of msg.tool_calls || []) {
    let input = {};
    try {
      input = JSON.parse(tc.function?.arguments || '{}');
    } catch {
      input = { __raw: tc.function?.arguments ?? '' };
    }
    content.push({
      type: 'tool_use',
      id: tc.id,
      name: tc.function?.name ?? '',
      input,
    });
  }
  if (!content.length) content.push({ type: 'text', text: '' });
  return {
    id: 'msg_' + (json.id || Math.random().toString(36).slice(2)),
    type: 'message',
    role: 'assistant',
    model: reqModel || model,
    content,
    stop_reason: STOP_MAP[choice.finish_reason] || 'end_turn',
    stop_sequence: null,
    usage: {
      input_tokens: json.usage?.prompt_tokens ?? 0,
      output_tokens: json.usage?.completion_tokens ?? 0,
    },
  };
}

// ---------- OpenAI stream -> Anthropic stream ----------
async function streamTranslate(upstream, res, reqModel) {
  const send = (event, data) =>
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

  const msgId = 'msg_' + Math.random().toString(36).slice(2);
  let nextIndex = 0;
  let openIndex = -1;
  let textIndex = -1;
  let inputTokens = 0;
  let outputTokens = 0;
  let finish = null;
  const tools = new Map(); // openai tool index -> {ai, id, name}

  const openBlock = (index, block) => {
    send('content_block_start', {
      type: 'content_block_start',
      index,
      content_block: block,
    });
    openIndex = index;
  };
  const closeBlock = () => {
    if (openIndex >= 0) {
      send('content_block_stop', { type: 'content_block_stop', index: openIndex });
      openIndex = -1;
    }
  };

  send('message_start', {
    type: 'message_start',
    message: {
      id: msgId,
      type: 'message',
      role: 'assistant',
      model: reqModel || model,
      content: [],
      stop_reason: null,
      stop_sequence: null,
      usage: { input_tokens: 0, output_tokens: 0 },
    },
  });

  function processChunk(json) {
    if (json.usage) {
      inputTokens = json.usage.prompt_tokens ?? inputTokens;
      outputTokens = json.usage.completion_tokens ?? outputTokens;
    }
    const choice = json.choices?.[0];
    if (!choice) return;
    const delta = choice.delta || {};

    if (typeof delta.content === 'string' && delta.content.length) {
      if (textIndex < 0) textIndex = nextIndex++;
      if (openIndex !== textIndex) {
        closeBlock();
        openBlock(textIndex, { type: 'text', text: '' });
      }
      send('content_block_delta', {
        type: 'content_block_delta',
        index: textIndex,
        delta: { type: 'text_delta', text: delta.content },
      });
    }

    for (const tcd of delta.tool_calls || []) {
      const oi = tcd.index ?? 0;
      let st = tools.get(oi);
      if (!st) {
        closeBlock();
        st = {
          ai: nextIndex++,
          id: tcd.id || 'toolu_' + Math.random().toString(36).slice(2),
          name: tcd.function?.name || '',
        };
        tools.set(oi, st);
        openBlock(st.ai, { type: 'tool_use', id: st.id, name: st.name, input: {} });
      } else if (openIndex !== st.ai) {
        closeBlock();
        openBlock(st.ai, { type: 'tool_use', id: st.id, name: st.name, input: {} });
      }
      if (tcd.id && !st.id) st.id = tcd.id;
      if (tcd.function?.name && !st.name) st.name = tcd.function.name;
      const args = tcd.function?.arguments;
      if (args) {
        send('content_block_delta', {
          type: 'content_block_delta',
          index: st.ai,
          delta: { type: 'input_json_delta', partial_json: args },
        });
      }
    }

    if (choice.finish_reason) finish = STOP_MAP[choice.finish_reason] || finish;
  }

  try {
    const reader = upstream.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (!data || data === '[DONE]') continue;
        let json;
        try {
          json = JSON.parse(data);
        } catch {
          continue;
        }
        processChunk(json);
      }
    }
  } catch (e) {
    log('stream error:', e.message);
  } finally {
    closeBlock();
    send('message_delta', {
      type: 'message_delta',
      delta: { stop_reason: finish || 'end_turn', stop_sequence: null },
      usage: { output_tokens: outputTokens },
    });
    send('message_stop', { type: 'message_stop' });
    res.end();
  }
}

// ---------- HTTP server ----------
async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const path = url.pathname;

  try {
    if (req.method === 'POST' && path.endsWith('/messages')) {
      const raw = await readBody(req);
      let body;
      try {
        body = JSON.parse(raw || '{}');
      } catch {
        res.writeHead(400, { 'content-type': 'application/json' });
        return res.end(
          JSON.stringify({
            type: 'error',
            error: { type: 'invalid_request_error', message: 'invalid JSON' },
          })
        );
      }
      const openaiBody = toOpenAI(body);
      if (process.env.PROXY_DEBUG) {
        log('DEBUG roles:', openaiBody.messages.map((m) => m.role).join(','));
        fs.writeFileSync('/tmp/claude_proxy_last.json', JSON.stringify(openaiBody, null, 2));
      }
      let up;
      try {
        up = await fetch(UPSTREAM, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            authorization: 'Bearer ' + apiKey,
          },
          body: JSON.stringify(openaiBody),
        });
      } catch (e) {
        res.writeHead(502, { 'content-type': 'application/json' });
        return res.end(
          JSON.stringify({
            type: 'error',
            error: { type: 'api_error', message: 'upstream fetch failed: ' + e.message },
          })
        );
      }
      if (!up.ok) {
        const t = await up.text();
        log('upstream', up.status, t.slice(0, 300));
        res.writeHead(up.status, { 'content-type': 'application/json' });
        return res.end(
          JSON.stringify({
            type: 'error',
            error: { type: 'api_error', message: t.slice(0, 2000) },
          })
        );
      }
      if (body.stream) {
        res.writeHead(200, {
          'content-type': 'text/event-stream',
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        });
        return await streamTranslate(up, res, body.model);
      }
      const j = await up.json();
      const anth = fromOpenAI(j, body.model);
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify(anth));
    }

    if (req.method === 'POST' && path.endsWith('/count_tokens')) {
      const raw = await readBody(req);
      let n = 0;
      try {
        const b = JSON.parse(raw || '{}');
        n = Math.ceil(JSON.stringify(b.messages ?? b).length / 4);
      } catch {}
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ input_tokens: n }));
    }

    if (path.endsWith('/models')) {
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(
        JSON.stringify({
          data: [
            {
              type: 'model',
              id: model,
              display_name: model,
              created_at: new Date().toISOString(),
            },
          ],
        })
      );
    }

    res.writeHead(404, { 'content-type': 'application/json' });
    res.end(
      JSON.stringify({
        type: 'error',
        error: { type: 'not_found_error', message: 'no route: ' + path },
      })
    );
  } catch (e) {
    log('handler error:', e.stack || e.message);
    if (!res.headersSent) res.writeHead(500, { 'content-type': 'application/json' });
    try {
      res.end(
        JSON.stringify({
          type: 'error',
          error: { type: 'api_error', message: e.message },
        })
      );
    } catch {}
  }
});

server.listen(port, host, () =>
  log(`anthropic->openai proxy on http://${host}:${port} => ${UPSTREAM} (${model})`)
);
