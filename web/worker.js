// Rendering and files remain in JS; all rules and seeded decisions live in Python.
const ROOT = new URL('./', import.meta.url);
const RUNTIME = 'https://cdn.jsdelivr.net/pyodide/v0.27.7/full/';
let bridge;
async function fetchText(path) {
  const r = await fetch(new URL(path, ROOT), {cache:'no-cache'});
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.text();
}
const ready = (async () => {
  postMessage({status:'Python 경기 엔진을 준비하고 있습니다…'});
  const {loadPyodide} = await import(`${RUNTIME}pyodide.mjs`);
  const [py, cards, champions] = await Promise.all([
    loadPyodide({indexURL:RUNTIME}), fetchText('data/cards.json'), fetchText('data/champions.json')
  ]);
  // RUNTIME_FILES_START
  for (const name of ['engine.py','progression.py','match_features.py','draft.py','combat.py','abilities.py','legacy_engine.py','legacy_engine_v2.py','legacy_abilities_v2.py','legacy_engine_v3.py','legacy_combat_v3.py']) {
    py.FS.writeFile(`/home/pyodide/${name}`, await fetchText(name), {encoding:'utf8'});
  }
  // RUNTIME_FILES_END
  const mod = py.pyimport('engine');
  bridge = mod.Bridge(cards, champions);
  mod.destroy();
})();
// Explicit queue: never interleave import/new/tick requests during initial loading.
let queue = Promise.resolve();
onmessage = ({data}) => {
  queue = queue.then(async () => {
    try {
      await ready;
      const result = JSON.parse(bridge.call(JSON.stringify(data.action)));
      postMessage({id:data.id, ...result});
    } catch (e) {
      postMessage({id:data.id, ok:false, error:`엔진을 불러오지 못했습니다. 인터넷 연결 또는 CDN 접근을 확인한 뒤 새로고침해 주세요. ${e.message}`});
    }
  });
};
ready.catch(() => {});
