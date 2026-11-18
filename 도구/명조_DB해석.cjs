// Decode extracted SQLite BinData with the matching client schema getters.
// No game modules are initialized; the loader permits only data schema/runtime files.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const [rootArg, inputArg, outputArg] = process.argv.slice(2);
if (!rootArg || !inputArg || !outputArg) throw new Error('Usage: node 명조_DB해석.cjs JavaScriptRoot input.json outputDir');
const root = path.resolve(rootArg), output = path.resolve(outputArg);
if (fs.existsSync(output)) throw new Error('Output already exists; use a new run directory');
const schemaDir = path.join(root, 'Core', 'Define', 'Config');
const cache = new Map();
const gameUtils = {GameUtils: {
  IsOptimizeDbString: false,
  InternalizedString() {},
  ConvertToArray(n, getter, owner) { return Array.from({length:n}, (_,i)=>getter.call(owner,i)); },
  ConvertToMap(n, key, value, owner) {
    return new Map(Array.from({length:n}, (_,i)=>[key.call(owner,i),value.call(owner,i)]));
  }
}};
const hashes = {};
function load(file) {
  file = path.resolve(file);
  if (cache.has(file)) return cache.get(file);
  const relative = path.relative(root, file).replaceAll('\\','/');
  if (!relative.startsWith('Core/Define/Config/') && !relative.startsWith('RunTimeLibs/FlatBuffers/')) throw new Error('Disallowed schema dependency: '+relative);
  const source = fs.readFileSync(file,'utf8');
  hashes[relative] = crypto.createHash('sha256').update(source).digest('hex');
  const exports = {};
  cache.set(file,exports);
  const context = vm.createContext({exports, module:{exports}, require: name => {
    if (name.endsWith('/Game/GameUtils')) return gameUtils;
    if (name.endsWith('/KuroTextEncoding/kuro-text-encoding')) return {TextDecoder,TextEncoder};
    if (!name.startsWith('.')) throw new Error('Disallowed external module: '+name);
    return load(path.resolve(path.dirname(file),name+'.js'));
  }}, {codeGeneration:{strings:false,wasm:false}});
  new vm.Script(source,{filename:relative}).runInContext(context,{timeout:1000});
  return exports;
}
function plain(value, depth=0) {
  if (depth>30) throw new Error('Excessive schema nesting');
  if (typeof value==='bigint') {
    if (value>BigInt(Number.MAX_SAFE_INTEGER)||value<BigInt(Number.MIN_SAFE_INTEGER)) return value.toString();
    return Number(value);
  }
  if (value===null || typeof value!=='object') return value;
  if (Array.isArray(value)) return value.map(v=>plain(v,depth+1));
  if (Object.prototype.toString.call(value)==='[object Map]') return Object.fromEntries(Array.from(value,([k,v])=>[k,plain(v,depth+1)]));
  const result = {};
  for (const [name,descriptor] of Object.entries(Object.getOwnPropertyDescriptors(Object.getPrototypeOf(value)))) {
    if (descriptor.get) result[name] = plain(value[name],depth+1);
  }
  return result;
}
const {ByteBuffer} = load(path.join(root,'RunTimeLibs','FlatBuffers','byte-buffer.js'));
const files = new Map(fs.readdirSync(schemaDir).filter(n=>n.endsWith('.js')).map(n=>[n.slice(0,-3).toLowerCase(),n]));
const input = JSON.parse(fs.readFileSync(inputArg,'utf8'));
const manifest = {input_sha256:crypto.createHash('sha256').update(fs.readFileSync(inputArg)).digest('hex'),tables:[],schemas:hashes};
fs.mkdirSync(output,{recursive:true});
let count=0;
for (const table of input.tables) {
  const file=files.get(table.name.toLowerCase());
  const record={database:table.database,table:table.name,rows:table.rows.length,source_sha256:table.sha256};
  if (!file) {manifest.tables.push({...record,status:'schema_not_extracted'});continue;}
  const schema=load(path.join(schemaDir,file));
  const className=file.slice(0,-3), constructor=schema[className];
  if (!constructor?.['getRootAs'+className]) throw new Error('Missing root constructor '+className);
  const rows=table.rows.map(row=>{
    const buffer=new ByteBuffer(new Uint8Array(Buffer.from(row.BinData,'base64')));
    const result=plain(constructor['getRootAs'+className](buffer));
    for (const [key,value] of Object.entries(row)) {
      if (key==='BinData') continue;
      const decoded = typeof result[key] === 'boolean' ? Number(result[key]) : result[key];
      if (Object.hasOwn(result,key) && decoded!==value) throw new Error(`${table.name}: SQLite/schema mismatch ${key}: ${value} != ${result[key]}`);
      if (!Object.hasOwn(result,key)) result[key]=value;
    }
    return result;
  });
  const data=JSON.stringify(rows,null,2)+'\n';
  fs.writeFileSync(path.join(output,table.name+'.json'),data);
  manifest.tables.push({...record,status:'client_table_verified',schema:file,sha256:crypto.createHash('sha256').update(data).digest('hex')});
  count+=rows.length;
}
fs.writeFileSync(path.join(output,'해석_명세.json'),JSON.stringify(manifest,null,2)+'\n');
console.log(JSON.stringify({tables:manifest.tables.filter(x=>x.status==='client_table_verified').length,rows:count,unsupported:manifest.tables.filter(x=>x.status!=='client_table_verified').map(x=>x.table)}));
