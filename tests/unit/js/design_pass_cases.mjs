/*
 * Behaviour cases for the #199 and #196 design pass.
 *
 * Run by `tests/unit/test_design_pass.py`, which shells out to node.
 *
 * Run rather than read, because the two things worth protecting are
 * behavioural: what `shortUrl` does to a real Maps link, and what
 * `nodeRadius` returns at each zoom. A source grep cannot tell you that
 * a regex shortens a URL correctly, and the URL handling carries a
 * security decision (they stay text, never anchors).
 *
 * `app.js` is one big script, not a module, so the functions under test
 * are extracted from the shipped file by name. If that extraction ever
 * fails, the harness says so rather than silently testing nothing --
 * see the guard at the bottom.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/app.js'), 'utf8');

/** Pull one top-level `function name(...) { ... }` out of the file. */
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  const end = source.indexOf('\n}', start);
  if (end < 0) throw new Error(`${name} has no closing brace`);
  return source.slice(start, end + 2);
}

function constant(name) {
  const start = source.indexOf(`const ${name} =`);
  if (start < 0) throw new Error(`${name} not found in app.js`);
  return source.slice(start, source.indexOf('\n', start) + 1);
}

const el = (tag, attrs = {}, ...kids) => ({
  tag, attrs, kids: kids.flat(), append(...more) { this.kids.push(...more); },
});

const api = new Function('el', [
  constant('URL_IN_TEXT'),
  extract('shortUrl'),
  extract('messageBody'),
  extract('nodeRadius'),
  constant('GATEWAY_RING_FROM_ZOOM'),
  'return { shortUrl, messageBody, nodeRadius, GATEWAY_RING_FROM_ZOOM };',
].join('\n'))(el);

let failed = 0;
const eq = (name, got, want) => {
  if (got === want) return;
  failed += 1;
  console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

// --- #199: URLs are shortened, and stay text -----------------------

eq('a maps link', api.shortUrl('https://www.google.com/maps?q=33.3543%2C-111.9112'),
  'google.com/maps');
eq('www is dropped', api.shortUrl('https://www.example.com/a'), 'example.com/a');
eq('a trailing slash goes', api.shortUrl('https://example.com/a/'), 'example.com/a');
eq('a long path keeps the host', api.shortUrl(`https://example.com/${'a'.repeat(60)}`),
  'example.com…');
// Rubbish must come back unchanged rather than throwing: a message body
// is arbitrary text and this runs on every message on the site.
eq('not a url at all', api.shortUrl('http://'), 'http://');

const parts = api.messageBody('see https://www.google.com/maps?q=1%2C2 and #tag here');
const kinds = parts.kids.map((k) => (typeof k === 'string' ? 'text' : k.attrs.class));
ok('the url becomes its own node', kinds.includes('link-text'), kinds.join(','));
ok('hashtags still work beside a url', kinds.includes('hash'), kinds.join(','));

const urlNode = parts.kids.find((k) => typeof k !== 'string' && k.attrs.class === 'link-text');
eq('the shown text is short', urlNode.attrs.text, 'google.com/maps');
eq('the full url is kept on the element',
  urlNode.attrs.title, 'https://www.google.com/maps?q=1%2C2');
// THE SECURITY CASE. A message body is text anyone on the mesh can
// send, and nothing checks who sent it.
eq('a url is NOT an anchor', urlNode.tag, 'span');
ok('no href anywhere on it', !('href' in urlNode.attrs), JSON.stringify(urlNode.attrs));

// Two URLs in one message, which is what a forwarded position looks like.
const two = api.messageBody('https://example.com/one then https://example.org/two');
const links = two.kids.filter((k) => typeof k !== 'string' && k.attrs.class === 'link-text');
eq('both urls are shortened', links.length, 2);
eq('the second is not swallowed', links[1].attrs.text, 'example.org/two');

// --- #196: dots that read at the opening zoom ----------------------

ok('the opening view uses small dots', api.nodeRadius(7) < 3, `got ${api.nodeRadius(7)}`);
ok('street level uses the largest', api.nodeRadius(16) > api.nodeRadius(13));
// Monotonic: a dot must never shrink as you zoom in.
let last = 0;
for (let z = 1; z <= 19; z += 1) {
  const r = api.nodeRadius(z);
  ok(`radius does not shrink at zoom ${z}`, r >= last, `${r} < ${last}`);
  last = r;
}
ok('the gateway ring waits for a readable zoom',
  api.GATEWAY_RING_FROM_ZOOM > 7, `got ${api.GATEWAY_RING_FROM_ZOOM}`);

if (failed) {
  console.error(`${failed} failed`);
  process.exit(1);
}
console.log('design pass: all cases passed');

// --- #193.6: a focused node keeps its mark -------------------------
//
// Appended after the #199/#196 cases because it reads the same
// `nodeStyle`. Extracted with the module's own globals stubbed, so the
// focus branch is exercised rather than described.

const styleSrc = [
  constant('GATEWAY_RING_FROM_ZOOM'),
  extract('nodeRadius'),
  extract('nodeStyle'),
  'return nodeStyle;',
].join('\n');

const makeStyle = (focusNodeId) => new Function(
  'mapState', 'nodeColour', 'isStale', 'PALETTE', styleSrc,
)({ focusNodeId }, () => '#123456', () => false,
  { muted: '#888888', accent: '#ff8800', text: '#000000' });

{
  const plain = makeStyle(null);
  const focused = makeStyle('!abc');
  const node = { node_id: '!abc', is_mqtt_gateway: false };
  const other = { node_id: '!zzz', is_mqtt_gateway: false };

  const marked = focused(node, 13);
  const unmarked = plain(node, 13);
  ok('a focused node is drawn wider', marked.radius > unmarked.radius,
    `${marked.radius} vs ${unmarked.radius}`);
  ok('a focused node is drawn thicker', marked.weight > unmarked.weight,
    `${marked.weight} vs ${unmarked.weight}`);
  eq('a focused node takes the accent', marked.color, '#ff8800');
  // Size AND hue, so the mark survives a greyscale render -- the rule
  // the live map's own layers follow.
  ok('the mark is not colour alone', marked.radius !== unmarked.radius);

  // The mark belongs to ONE node.
  const neighbour = focused(other, 13);
  eq('another node is untouched', neighbour.radius, unmarked.radius);
  ok('another node keeps its role colour', neighbour.color !== '#ff8800');

  // And it survives a zoom change, because it is computed per call.
  for (const z of [7, 10, 13, 17]) {
    ok(`the mark holds at zoom ${z}`, focused(node, z).weight > plain(node, z).weight);
  }
}

if (failed) {
  console.error(`${failed} failed`);
  process.exit(1);
}
console.log('focus mark: all cases passed');

// --- a failed request says WHICH request -----------------------------
//
// "Request failed (500)" was the whole message. A page that makes six
// requests then reports one number, and neither the reader nor a
// maintainer reading the bug report can tell which one broke. A real 500
// on the node page cost a scan of every endpoint at every window value
// to chase, and is still unreproduced.

{
  const src2 = source;
  const start = src2.indexOf('function requestFailed(');
  ok('requestFailed exists', start > 0);
  const body = src2.slice(start, src2.indexOf('\n}', start) + 2);
  const requestFailed = new Function(`${body}; return requestFailed;`)();

  const e = requestFailed('api/nodes/%21abcd1234/detail?hours=720', 500);
  ok('names the status', e.message.includes('500'), e.message);
  ok('names the path', e.message.includes('api/nodes/%21abcd1234/detail'), e.message);
  // No query string: it carries node ids, and this message can end up in
  // a screenshot or an issue.
  ok('drops the query string', !e.message.includes('hours=720'), e.message);
  ok('it is an Error', e instanceof Error);

  // The firehose distinguishes a 422 by testing the message. That test
  // must keep working now the path is appended.
  const filter = requestFailed('api/packets?type=nope', 422);
  ok('a 422 is still recognisable by /422/', /422/.test(filter.message), filter.message);
}

if (failed) { console.error(`${failed} failed`); process.exit(1); }
console.log('request errors: all cases passed');
