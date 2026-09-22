#!/usr/bin/env node
/**
 * arch-lens TypeScript extractor: what each changed file calls, resolved by the type checker.
 *
 * Walks the workspace with the TypeScript compiler API, so every call site resolves to the
 * declaration it actually reaches: a function in another package, a member of an interface
 * (a "port": `storage.files.get` → IFileStore.get), a property of an inferred object, or a
 * platform global such as `fetch`. Emits JSON for arch-lens (never HTML):
 *   nodes      files in package lanes (changed, reached from a change, callers, externals)
 *   edges      resolved CALLS, not imports, with the symbols called and their call sites;
 *              interface implementations as «implements» edges
 *   flows      mermaid sequence diagrams from entry functions through the call graph, in
 *              source order; a call through an interface fans out into `alt` branches
 *   contracts  exported members of every node with checker-printed signatures
 *
 * Usage: node extract.js --config <file.json>   (arch-lens writes that file; see cli.py)
 * TypeScript is resolved from the workspace itself; nothing is installed.
 */

'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const cfg = loadConfig(process.argv.slice(2));
const REPO = cfg.repo;
const ROOT_PREFIX = cfg.root.replace(/\/+$/, '') + '/';
const ROOT = path.join(REPO, ROOT_PREFIX);
const ts = require(require.resolve('typescript', {paths: [ROOT, REPO, process.cwd()]}));

const EXTERNAL_TARGETS = (cfg.externals || []).map((e) => ({
  id: `ext:${e.id}`, label: e.label, kind: e.kind || 'external', file: new RegExp(e.file), name: new RegExp(e.name),
}));
const matchExternal = (file, name) => EXTERNAL_TARGETS.find((e) => e.file.test(file) && e.name.test(name));
const extAlias = (id) => 'x_' + id.replace(/^ext:/, '').replace(/[^A-Za-z0-9_]/g, '_');

function loadConfig(argv) {
  const index = argv.indexOf('--config');
  if (index === -1 || !argv[index + 1]) {
    console.error('usage: extract.js --config <file.json>');
    process.exit(2);
  }
  const loaded = JSON.parse(fs.readFileSync(argv[index + 1], 'utf8'));
  return {
    srcDir: 'src', tsconfig: 'tsconfig.json', seeds: [], entry: [], link: [], focus: [], ignore: [], scopePackages: [],
    hops: 2, inHops: 1, anchorHops: 1, maxCallers: 8, maxFlows: 8, depth: 8, expandJsx: false, showHubs: false,
    ...loaded,
  };
}

// ---------------------------------------------------------------------------------------
// git: changed line ranges against the merge-base (the working tree included)
// ---------------------------------------------------------------------------------------

function git(argsList) {
  return cp.execFileSync('git', argsList, {cwd: REPO, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024});
}

function changedLineRanges(file) {
  const diff = git(['diff', '-U0', cfg.baseSha, '--', file]);
  const ranges = [];
  for (const hunk of diff.matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)) {
    const start = Number(hunk[1]);
    const length = hunk[2] === undefined ? 1 : Number(hunk[2]);
    if (length > 0) ranges.push([start, start + length - 1]);
  }
  return ranges;
}

const intersects = (ranges, startLine, endLine) => ranges.some(([a, b]) => a <= endLine && b >= startLine);

// ---------------------------------------------------------------------------------------
// paths
// ---------------------------------------------------------------------------------------

const toPosix = (p) => p.split(path.sep).join('/');
const relOf = (absolute) => toPosix(path.relative(REPO, absolute));
const inWorkspace = (rel) => rel.startsWith(ROOT_PREFIX) && !rel.includes('/node_modules/');
const isSource = (rel) => /\.(ts|tsx|js|jsx)$/.test(rel);
const isTest = (rel) => /\.(test|spec)\.[jt]sx?$|\/__mocks__\/|\/__tests__\/|\.stories\.|vitest\.setup|jest\.setup/.test(rel);
const pkgOf = (rel) => {
  if (!inWorkspace(rel)) return 'external';
  const inside = rel.slice(ROOT_PREFIX.length);
  return inside.includes('/') ? inside.split('/')[0] : 'root';
};
const shortName = (rel) => path.posix.basename(rel);
/** `index.ts` says nothing on its own: barrels and adapters are named by their folder. */
const displayLabel = (rel) => {
  const base = shortName(rel);
  return /^index\.[jt]sx?$/.test(base) ? `${path.posix.basename(path.posix.dirname(rel))}/${base}` : base;
};

function listSourceFiles(packages) {
  const files = [];
  const keep = (full) => {
    const rel = relOf(full);
    if (isSource(rel) && !isTest(rel) && !rel.endsWith('.d.ts')) files.push(full);
  };
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else keep(full);
    }
  };
  for (const pkg of packages) {
    if (pkg === 'root') {
      for (const entry of fs.readdirSync(ROOT, {withFileTypes: true})) if (entry.isFile()) keep(path.join(ROOT, entry.name));
      continue;
    }
    const withSrc = cfg.srcDir ? path.join(ROOT, pkg, cfg.srcDir) : null;
    const dir = withSrc && fs.existsSync(withSrc) ? withSrc : path.join(ROOT, pkg);
    if (fs.existsSync(dir) && fs.statSync(dir).isDirectory()) walk(dir);
  }
  return files;
}

// ---------------------------------------------------------------------------------------
// TypeScript program
// ---------------------------------------------------------------------------------------

function createProgram(rootFiles) {
  const cfgPath = path.join(ROOT, cfg.tsconfig);
  let options = {};
  if (fs.existsSync(cfgPath)) {
    const read = ts.readConfigFile(cfgPath, ts.sys.readFile);
    if (read.error) throw new Error(ts.flattenDiagnosticMessageText(read.error.messageText, '\n'));
    options = ts.parseJsonConfigFileContent(read.config, ts.sys, path.dirname(cfgPath)).options;
  }
  return ts.createProgram(rootFiles, {
    ...options, noEmit: true, allowJs: true, checkJs: false, skipLibCheck: true, jsx: ts.JsxEmit.ReactJSX, incremental: false,
  });
}

// ---------------------------------------------------------------------------------------
// naming: the dotted chain of named ancestors (Checkout.handleSubmit, strategies.card.pay)
// ---------------------------------------------------------------------------------------

const unquote = (text) => text.replace(/^['"`]|['"`]$/g, '');

function ownName(node) {
  if (ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node) || ts.isMethodDeclaration(node)) {
    return node.name ? unquote(node.name.getText()) : null;
  }
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) return node.name.text;
  if (ts.isPropertyAssignment(node)) return unquote(node.name.getText());
  return null;
}

function chainOf(node) {
  const names = [];
  for (let current = node; current && !ts.isSourceFile(current); current = current.parent) {
    const name = ownName(current);
    if (name) names.unshift(name);
  }
  return names.join('.') || '<module>';
}

function isFunctionLike(node) {
  return ts.isArrowFunction(node) || ts.isFunctionExpression(node) || ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node);
}

/** A function with a name of its own is the unit flows walk; anonymous callbacks
 * (`useEffect(() => …)`, `.then(() => …)`) belong to their nearest named ancestor. */
function isNamedFunction(node) {
  if (ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) return Boolean(node.name);
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
    return (ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name)) || ts.isPropertyAssignment(node.parent);
  }
  return false;
}

function enclosingNamedFunction(node) {
  for (let current = node.parent; current && !ts.isSourceFile(current); current = current.parent) {
    if (isFunctionLike(current) && isNamedFunction(current)) return current;
  }
  return null;
}

function isCallableDeclaration(decl) {
  if (ts.isFunctionDeclaration(decl) || ts.isMethodDeclaration(decl) || ts.isClassDeclaration(decl) || isFunctionLike(decl)) return true;
  if (ts.isVariableDeclaration(decl) || ts.isPropertyAssignment(decl)) {
    const init = decl.initializer;
    if (!init) return false;
    if (isFunctionLike(init)) return true;
    if (ts.isCallExpression(init) && /^(React\.)?(memo|forwardRef|styled|connect|observer)\b/.test(init.expression.getText())) return true;
  }
  return false;
}

function functionKeyOfDeclaration(decl) {
  if ((ts.isVariableDeclaration(decl) || ts.isPropertyAssignment(decl)) && decl.initializer && isFunctionLike(decl.initializer)) {
    return chainOf(decl.initializer);
  }
  return chainOf(decl);
}

function isExported(decl) {
  try {
    return Boolean(ts.getCombinedModifierFlags(decl) & ts.ModifierFlags.Export);
  } catch (error) {
    return false;
  }
}

function packageOfExternal(absolute) {
  const posix = toPosix(absolute);
  if (/\/typescript(@[^/]+)?\/lib\/lib\.[^/]*\.d\.ts$/.test(posix)) return 'web platform';
  // pnpm keeps the real package under node_modules/.pnpm/<name>@<version>/node_modules/<name>
  const pnpm = posix.match(/node_modules\/\.pnpm\/[^/]+\/node_modules\/((?:@[^/]+\/)?[^/]+)/);
  if (pnpm) return pnpm[1];
  const match = posix.match(/node_modules\/((?:@[^/]+\/)?[^/]+)/);
  if (match && match[1] !== '.pnpm') return match[1];
  return 'external';
}

const truncate = (text, max) => (text.length > max ? text.slice(0, max - 1) + '…' : text);

// ---------------------------------------------------------------------------------------
// extraction
// ---------------------------------------------------------------------------------------

class Extractor {
  constructor(program, ranges) {
    this.checker = program.getTypeChecker();
    this.ranges = ranges; // rel -> [[start, end]]
    this.functions = new Map(); // "rel#key" -> {file, key, name, startLine, endLine, changed, params, exported, calls}
    this.impls = []; // {iface, ifaceName, member, implFile, implFn, at, via}
    this.visited = new Set();
  }

  lineOf(sf, pos) { return sf.getLineAndCharacterOfPosition(pos).line + 1; }

  isIgnored(rel) { return cfg.ignore.some((fragment) => rel.includes(fragment)); }

  registerFunction(sf, rel, node) {
    const key = chainOf(node);
    const id = `${rel}#${key}`;
    if (this.functions.has(id)) return this.functions.get(id);
    const startLine = this.lineOf(sf, node.getStart(sf));
    const endLine = this.lineOf(sf, node.getEnd());
    const owner = ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node) ? node : node.parent;
    const entry = {
      id, file: rel, key, name: key.split('.').pop(), startLine, endLine,
      changed: intersects(this.ranges[rel] || [], startLine, endLine),
      params: (node.parameters || []).map((p) => p.name.getText(sf).replace(/\s+/g, ' ')).filter((p) => !p.startsWith('{') || p.length < 40),
      exported: ts.isPropertyAssignment(owner) ? false : isExported(owner),
      calls: [],
    };
    this.functions.set(id, entry);
    return entry;
  }

  moduleFunction(rel) {
    const id = `${rel}#<module>`;
    if (!this.functions.has(id)) {
      this.functions.set(id, {id, file: rel, key: '<module>', name: '<module>', startLine: 1, endLine: 1, changed: false, params: [], exported: false, calls: []});
    }
    return this.functions.get(id);
  }

  /** The declarations a callee resolves to (several for a property of a union). */
  resolveTargets(calleeNode) {
    let symbol;
    try { symbol = this.checker.getSymbolAtLocation(calleeNode); } catch (error) { return []; }
    if (!symbol) return [];
    if (symbol.flags & ts.SymbolFlags.Alias) {
      try { symbol = this.checker.getAliasedSymbol(symbol); } catch (error) { return []; }
    }
    const targets = [];
    for (let decl of symbol.declarations || []) {
      for (let hop = 0; hop < 3 && (ts.isPropertyAssignment(decl) || ts.isVariableDeclaration(decl)) && decl.initializer && ts.isIdentifier(decl.initializer); hop++) {
        let named;
        try { named = this.checker.getSymbolAtLocation(decl.initializer); } catch (error) { break; }
        if (named && named.flags & ts.SymbolFlags.Alias) named = this.checker.getAliasedSymbol(named);
        const namedDecl = named && named.declarations && named.declarations[0];
        if (!namedDecl || namedDecl === decl) break;
        decl = namedDecl;
      }
      if (ts.isShorthandPropertyAssignment(decl)) {
        let valueSymbol = this.checker.getShorthandAssignmentValueSymbol(decl);
        if (valueSymbol && valueSymbol.flags & ts.SymbolFlags.Alias) valueSymbol = this.checker.getAliasedSymbol(valueSymbol);
        const valueDecl = valueSymbol && valueSymbol.declarations && valueSymbol.declarations[0];
        if (valueDecl) decl = valueDecl;
      }
      const declFile = decl.getSourceFile();
      const declRel = relOf(declFile.fileName);
      const name = symbol.getName();
      const external = matchExternal(toPosix(declFile.fileName), name);
      const isPortMember = (ts.isPropertySignature(decl) || ts.isMethodSignature(decl)) && decl.parent && (ts.isInterfaceDeclaration(decl.parent) || ts.isTypeLiteralNode(decl.parent));
      let ifaceName = null;
      if (isPortMember) {
        if (ts.isInterfaceDeclaration(decl.parent)) ifaceName = decl.parent.name.text;
        else if (ts.isTypeAliasDeclaration(decl.parent.parent)) ifaceName = decl.parent.parent.name.text;
        else ifaceName = '(type literal)';
      }
      targets.push({
        name,
        file: declRel,
        workspace: inWorkspace(declRel) && !declRel.endsWith('.d.ts'),
        external: external ? external.id : null,
        externalPackage: !inWorkspace(declRel) ? packageOfExternal(declFile.fileName) : null,
        port: isPortMember ? {ifaceFile: declRel, ifaceName, member: name} : null,
        callable: !isPortMember && isCallableDeclaration(decl),
        fnKey: isPortMember ? null : functionKeyOfDeclaration(decl),
      });
    }
    return targets;
  }

  visitFile(sf) {
    const rel = relOf(sf.fileName);
    if (this.visited.has(rel)) return;
    this.visited.add(rel);
    const visit = (node) => {
      if (isFunctionLike(node) && isNamedFunction(node)) this.registerFunction(sf, rel, node);
      let calleeNode = null;
      let callText = null;
      if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
        const expr = node.expression;
        if (ts.isPropertyAccessExpression(expr)) calleeNode = expr.name;
        else if (ts.isIdentifier(expr)) calleeNode = expr;
        callText = expr.getText(sf);
      } else if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const tag = node.tagName;
        calleeNode = ts.isPropertyAccessExpression(tag) ? tag.name : tag;
        callText = `<${tag.getText(sf)}>`;
      }
      if (calleeNode) {
        const targets = this.resolveTargets(calleeNode);
        if (targets.length) {
          const enclosing = enclosingNamedFunction(node);
          const fn = enclosing ? this.registerFunction(sf, rel, enclosing) : this.moduleFunction(rel);
          const argText = ts.isCallExpression(node) || ts.isNewExpression(node)
            ? (node.arguments || []).map((a) => a.getText(sf).replace(/\s+/g, ' ')).join(', ')
            : '';
          fn.calls.push({
            line: this.lineOf(sf, node.getStart(sf)),
            text: truncate(callText, 60),
            args: truncate(argText, 70),
            jsx: callText.startsWith('<'),
            targets,
          });
        }
      }
      if (ts.isObjectLiteralExpression(node)) this.collectImplementations(sf, rel, node);
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }

  /** An object literal typed by a workspace interface implements that interface's members. */
  collectImplementations(sf, rel, node) {
    let contextual;
    try { contextual = this.checker.getContextualType(node); } catch (error) { return; }
    if (!contextual) return;
    const ifaceSymbol = contextual.aliasSymbol || contextual.getSymbol();
    const ifaceDecl = ifaceSymbol && (ifaceSymbol.declarations || []).find((d) => ts.isInterfaceDeclaration(d) || ts.isTypeAliasDeclaration(d));
    if (!ifaceDecl) return;
    const ifaceRel = relOf(ifaceDecl.getSourceFile().fileName);
    if (!inWorkspace(ifaceRel)) return;
    for (const prop of node.properties) {
      if (!prop.name) continue;
      const member = unquote(prop.name.getText(sf));
      let implFile = null;
      let implFn = null;
      let valueSymbol = null;
      if (ts.isShorthandPropertyAssignment(prop)) valueSymbol = this.checker.getShorthandAssignmentValueSymbol(prop);
      else if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.initializer)) valueSymbol = this.checker.getSymbolAtLocation(prop.initializer);
      else if (ts.isPropertyAssignment(prop) && isFunctionLike(prop.initializer)) { implFile = rel; implFn = chainOf(prop.initializer); }
      else if (ts.isMethodDeclaration(prop)) { implFile = rel; implFn = chainOf(prop); }
      if (valueSymbol) {
        if (valueSymbol.flags & ts.SymbolFlags.Alias) valueSymbol = this.checker.getAliasedSymbol(valueSymbol);
        const decl = valueSymbol.declarations && valueSymbol.declarations[0];
        if (decl) { implFile = relOf(decl.getSourceFile().fileName); implFn = functionKeyOfDeclaration(decl); }
      }
      if (!implFile || !inWorkspace(implFile)) continue;
      this.impls.push({iface: ifaceRel, ifaceName: ifaceDecl.name.text, member, implFile, implFn, at: `${rel}:${this.lineOf(sf, prop.getStart(sf))}`, via: chainOf(node)});
    }
  }

  exportsOf(sf) {
    const rel = relOf(sf.fileName);
    let moduleSymbol;
    try { moduleSymbol = this.checker.getSymbolAtLocation(sf); } catch (error) { return []; }
    if (!moduleSymbol) return [];
    const out = [];
    for (let symbol of this.checker.getExportsOfModule(moduleSymbol)) {
      if (symbol.flags & ts.SymbolFlags.Alias) {
        try { symbol = this.checker.getAliasedSymbol(symbol); } catch (error) { continue; }
      }
      const decl = (symbol.declarations || [])[0];
      if (!decl) continue;
      const declSf = decl.getSourceFile();
      const declRel = relOf(declSf.fileName);
      const entry = {
        name: symbol.getName(),
        kind: ts.isInterfaceDeclaration(decl) ? 'interface' : ts.isTypeAliasDeclaration(decl) ? 'type' : ts.isClassDeclaration(decl) ? 'class' : ts.isEnumDeclaration(decl) ? 'enum' : 'value',
        reexport: declRel !== rel ? declRel : null,
        changed: intersects(this.ranges[declRel] || [], this.lineOf(declSf, decl.getStart(declSf)), this.lineOf(declSf, decl.getEnd())),
        signature: '',
        members: [],
      };
      try {
        if (entry.kind === 'interface') {
          for (const member of decl.members) {
            if (!member.name) continue;
            const memberSymbol = this.checker.getSymbolAtLocation(member.name);
            const type = memberSymbol ? this.checker.getTypeOfSymbolAtLocation(memberSymbol, member) : null;
            entry.members.push({
              name: member.name.getText(declSf),
              signature: type ? truncate(this.checker.typeToString(type, member, ts.TypeFormatFlags.NoTruncation), 150) : '',
              changed: intersects(this.ranges[declRel] || [], this.lineOf(declSf, member.getStart(declSf)), this.lineOf(declSf, member.getEnd())),
            });
          }
        } else if (entry.kind === 'value' || entry.kind === 'class') {
          entry.signature = truncate(this.checker.typeToString(this.checker.getTypeOfSymbolAtLocation(symbol, decl), decl, ts.TypeFormatFlags.NoTruncation), 170);
        } else if (entry.kind === 'type') {
          entry.signature = truncate(this.checker.typeToString(this.checker.getDeclaredTypeOfSymbol(symbol), decl, ts.TypeFormatFlags.NoTruncation | ts.TypeFormatFlags.InTypeAlias), 170);
        }
      } catch (error) {
        entry.signature = '';
      }
      out.push(entry);
    }
    return out;
  }
}

// ---------------------------------------------------------------------------------------
// graph assembly
// ---------------------------------------------------------------------------------------

function buildGraph(extractor, seeds, deltaSources, sfByRel) {
  const {hops, inHops, maxCallers, expandJsx, anchorHops} = cfg;
  const seedSet = new Set(seeds);
  const deltaSet = new Set(deltaSources);
  const nodes = new Map();
  const addNode = (rel, props) => {
    if (!nodes.has(rel)) nodes.set(rel, {id: rel, label: displayLabel(rel), pkg: pkgOf(rel), changed: false, seed: false, distance: null, hub: false, ...props});
    else Object.assign(nodes.get(rel), Object.fromEntries(Object.entries(props).filter(([k, v]) => v === true || (k === 'distance' && v !== null))));
    return nodes.get(rel);
  };
  const visitRel = (rel) => {
    const sf = sfByRel.get(rel);
    if (sf) extractor.visitFile(sf);
    return Boolean(sf);
  };

  // 1. seeds: the delta plus the anchors
  for (const rel of seeds) if (visitRel(rel)) addNode(rel, {seed: true, distance: 0});

  // 2. every scope file whose text names an export (or the basename) of a seed is visited,
  //    so callers are confirmed by resolution and hubs are measured over real call sites
  const exportNames = new Set();
  for (const rel of nodes.keys()) {
    const sf = sfByRel.get(rel);
    if (!sf) continue;
    for (const ex of extractor.exportsOf(sf)) exportNames.add(ex.name);
    exportNames.add(shortName(rel).replace(/\.[jt]sx?$/, ''));
  }
  const names = [...exportNames].filter((n) => n.length > 2).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const nameRegex = names.length ? new RegExp(`\\b(${names.join('|')})\\b`) : null;
  if (nameRegex && inHops > 0) {
    for (const [rel, sf] of sfByRel) if (!extractor.visited.has(rel) && nameRegex.test(sf.text)) extractor.visitFile(sf);
  }

  // 3. hubs: files called from more than maxCallers distinct files are infrastructure;
  //    drawn when a seed calls them, never expanded, their callers counted, not drawn
  const callerFiles = new Map();
  const tally = () => {
    callerFiles.clear();
    for (const fn of extractor.functions.values()) {
      if (isTest(fn.file)) continue;
      for (const call of fn.calls) for (const target of call.targets) {
        if (!target.workspace) continue;
        const file = target.port ? target.port.ifaceFile : target.file;
        if (file === fn.file) continue;
        if (!callerFiles.has(file)) callerFiles.set(file, new Set());
        callerFiles.get(file).add(fn.file);
      }
    }
  };
  tally();
  const callerCount = (rel) => (callerFiles.get(rel) || new Set()).size;
  const isHub = (rel) => callerCount(rel) > maxCallers;

  // 4. outward hops through resolved calls. A changed file expands only from its changed
  //    functions; an anchor from all of them but for anchorHops; a hub never.
  const expandingFunctions = (rel) => {
    const own = [...extractor.functions.values()].filter((fn) => fn.file === rel);
    if (deltaSet.has(rel)) return own.filter((fn) => fn.changed);
    if (isHub(rel)) return [];
    return own;
  };
  const outgoingFiles = (rel) => {
    const out = new Set();
    for (const fn of expandingFunctions(rel)) {
      for (const call of fn.calls) {
        if (call.jsx && !expandJsx) continue;
        for (const target of call.targets) {
          const file = target.port ? target.port.ifaceFile : target.file;
          if (target.workspace && !isTest(file) && !extractor.isIgnored(file) && file !== rel) out.add(file);
        }
      }
    }
    return out;
  };
  const budget = new Map();
  for (const rel of nodes.keys()) budget.set(rel, deltaSet.has(rel) ? hops : anchorHops);
  let frontier = [...nodes.keys()];
  for (let hop = 1; hop <= Math.max(hops, anchorHops); hop++) {
    const next = [];
    for (const rel of frontier) {
      if ((budget.get(rel) || 0) <= 0) continue;
      for (const target of outgoingFiles(rel)) {
        if (isHub(target) && !deltaSet.has(rel) && !nodes.has(target) && hop > 1) continue;
        if (!nodes.has(target)) {
          if (!visitRel(target)) continue;
          addNode(target, {distance: hop});
        }
        const left = budget.get(rel) - 1;
        if (left > (budget.get(target) || 0) && !nodes.get(target).seed) {
          budget.set(target, left);
          if (left > 0) next.push(target);
        }
      }
    }
    frontier = [...new Set(next)];
    tally();
  }

  // 5. the implementations of every interface member a node calls
  const usedPorts = new Set();
  for (const fn of extractor.functions.values()) {
    if (!nodes.has(fn.file)) continue;
    for (const call of fn.calls) for (const target of call.targets) {
      if (target.port) usedPorts.add(`${target.port.ifaceFile}#${target.port.ifaceName}.${target.port.member}`);
    }
  }
  for (const impl of extractor.impls) {
    if (!usedPorts.has(`${impl.iface}#${impl.ifaceName}.${impl.member}`)) continue;
    if (nodes.has(impl.iface) && !nodes.has(impl.implFile) && !isTest(impl.implFile) && !extractor.isIgnored(impl.implFile)) {
      if (visitRel(impl.implFile)) addNode(impl.implFile, {distance: (nodes.get(impl.iface).distance || 0) + 1, viaPort: true});
    }
  }
  tally();

  // 6. callers of the seeds (each further in-hop repeats over the callers just added)
  const collapsedCallers = {};
  let callerFrontier = [...seedSet].filter((rel) => nodes.has(rel));
  for (let hop = 1; hop <= inHops; hop++) {
    const next = [];
    for (const target of callerFrontier) {
      if (isHub(target)) { collapsedCallers[target] = callerCount(target); continue; }
      for (const caller of callerFiles.get(target) || []) {
        if (nodes.has(caller) || extractor.isIgnored(caller) || isTest(caller)) continue;
        addNode(caller, {distance: -hop, caller: true});
        next.push(caller);
      }
    }
    callerFrontier = next;
  }
  for (const node of nodes.values()) node.hub = isHub(node.id);

  // 7. edges among nodes, plus the external boundary targets
  const edges = new Map();
  const externals = new Map();
  const addEdge = (from, to, kind, symbol, site) => {
    const id = `${from}->${to}|${kind}`;
    if (!edges.has(id)) edges.set(id, {from, to, kind, symbols: new Map(), sites: []});
    const edge = edges.get(id);
    edge.symbols.set(symbol, (edge.symbols.get(symbol) || 0) + 1);
    if (edge.sites.length < 40) edge.sites.push(site);
  };
  for (const fn of extractor.functions.values()) {
    if (!nodes.has(fn.file)) continue;
    for (const call of fn.calls) for (const target of call.targets) {
      const site = {fn: fn.key, line: call.line, text: call.text};
      if (target.external) {
        const ext = EXTERNAL_TARGETS.find((e) => e.id === target.external);
        if (!externals.has(ext.id)) externals.set(ext.id, {id: ext.id, label: ext.label, pkg: 'external', external: true});
        addEdge(fn.file, ext.id, 'call', target.name, site);
        continue;
      }
      if (!target.workspace) continue;
      const targetFile = target.port ? target.port.ifaceFile : target.file;
      if (targetFile === fn.file || !nodes.has(targetFile)) continue;
      const symbol = target.port ? `${target.port.ifaceName}.${target.port.member}()` : call.jsx ? `<${target.name}>` : `${target.name}()`;
      addEdge(fn.file, targetFile, target.port ? 'port' : 'call', symbol, site);
    }
  }
  for (const impl of extractor.impls) {
    if (nodes.has(impl.iface) && nodes.has(impl.implFile) && impl.iface !== impl.implFile) {
      addEdge(impl.implFile, impl.iface, 'implements', `${impl.ifaceName}.${impl.member}`, {fn: impl.via, line: Number(impl.at.split(':').pop()), text: `${impl.member}: ${impl.implFn}`});
    }
  }
  for (const link of cfg.link.map(parseLink).filter(Boolean)) {
    if (nodes.has(link.from.file) && nodes.has(link.to.file) && link.from.file !== link.to.file) {
      addEdge(link.from.file, link.to.file, 'declared', link.label, {fn: link.from.fn, line: 0, text: `→ ${link.to.fn}`});
    }
  }
  for (const ext of externals.values()) nodes.set(ext.id, ext);

  return {
    nodes: [...nodes.values()],
    edges: [...edges.values()].map((e) => ({...e, symbols: [...e.symbols.entries()].sort((a, b) => b[1] - a[1]).map(([symbol, count]) => ({symbol, count}))})),
    collapsedCallers,
    hubs: [...nodes.keys()].filter(isHub),
  };
}

/** `--link 'a.ts#fn=b.ts#fn:label'` declares a bridge the checker cannot see (an event bus,
 * a message channel) so flows can cross it. */
function parseLink(spec) {
  const match = spec.match(/^([^#]+)#([^=]+)=([^#]+)#([^:]+)(?::(.*))?$/);
  if (!match) return null;
  return {from: {file: match[1], fn: match[2]}, to: {file: match[3], fn: match[4]}, label: match[5] || 'declared link'};
}

// ---------------------------------------------------------------------------------------
// flows: sequence diagrams from the function-level call graph, in source order
// ---------------------------------------------------------------------------------------

function buildFlows(extractor, graph, seeds) {
  const nodeIds = new Set(graph.nodes.map((n) => n.id));
  const seedSet = new Set(seeds);
  const hubs = new Set(graph.hubs.filter((h) => !seedSet.has(h)));
  const functions = extractor.functions;
  const implsByPort = new Map();
  for (const impl of extractor.impls) {
    const key = `${impl.iface}#${impl.ifaceName}.${impl.member}`;
    if (!implsByPort.has(key)) implsByPort.set(key, []);
    if (!implsByPort.get(key).some((i) => i.implFile === impl.implFile && i.implFn === impl.implFn)) implsByPort.get(key).push(impl);
  }
  const declaredLinks = cfg.link.map(parseLink).filter(Boolean);

  const successors = (fn) => {
    const out = [];
    for (const call of fn.calls) {
      if (call.jsx && !cfg.expandJsx) continue;
      const resolved = [];
      for (const target of call.targets) {
        if (target.external) { resolved.push({kind: 'external', call, label: target.name, ext: target.external}); continue; }
        if (!target.workspace || extractor.isIgnored(target.file) || isTest(target.file)) continue;
        if (target.port) {
          const impls = implsByPort.get(`${target.port.ifaceFile}#${target.port.ifaceName}.${target.port.member}`) || [];
          resolved.push({kind: 'port', call, target, impls: impls.map((i) => ({fn: functions.get(`${i.implFile}#${i.implFn}`), impl: i, hub: hubs.has(i.implFile)})).filter((i) => i.fn)});
          continue;
        }
        if (!target.callable) continue;
        const isHubTarget = hubs.has(target.file) && target.file !== fn.file;
        if (isHubTarget && !cfg.showHubs) continue;
        const targetFn = functions.get(`${target.file}#${target.fnKey}`);
        if (targetFn) resolved.push({kind: 'fn', call, target, fn: targetFn, hub: isHubTarget});
      }
      if (resolved.length) out.push({call, resolved});
    }
    for (const link of declaredLinks) {
      if (link.from.file === fn.file && link.from.fn === fn.key) {
        const targetFn = functions.get(`${link.to.file}#${link.to.fn}`);
        if (targetFn) out.push({call: {line: 0, text: link.label, args: '', jsx: false}, resolved: [{kind: 'fn', call: {text: link.label, args: ''}, target: {name: link.to.fn}, fn: targetFn, declared: link.label}]});
      }
    }
    return out;
  };

  const incoming = new Map();
  for (const fn of functions.values()) {
    if (!nodeIds.has(fn.file)) continue;
    for (const step of successors(fn)) for (const r of step.resolved) {
      if (r.kind === 'fn' && r.fn.id !== fn.id) incoming.set(r.fn.id, (incoming.get(r.fn.id) || 0) + 1);
      if (r.kind === 'port') for (const i of r.impls) incoming.set(i.fn.id, (incoming.get(i.fn.id) || 0) + 1);
    }
  }
  const reachableChanged = (root) => {
    const seen = new Set();
    const changed = new Set();
    const stack = [root];
    while (stack.length && seen.size < 400) {
      const fn = stack.pop();
      if (seen.has(fn.id)) continue;
      seen.add(fn.id);
      if (fn.changed) changed.add(fn.id);
      for (const step of successors(fn)) for (const r of step.resolved) {
        if (r.kind === 'fn' && !r.hub) stack.push(r.fn);
        if (r.kind === 'port') for (const i of r.impls) if (!i.hub) stack.push(i.fn);
      }
    }
    return changed;
  };

  // roots: explicit entries, then uncalled seed functions ranked by how much changed code
  // they reach that no earlier root already reaches
  const roots = [];
  for (const spec of cfg.entry) {
    const [file, key] = spec.split('#');
    const fn = functions.get(`${file}#${key}`);
    if (fn) roots.push({fn, why: 'entry'});
    else console.error(`entry not found: ${spec}`);
  }
  const candidates = [];
  for (const fn of functions.values()) {
    if (!seedSet.has(fn.file) || (incoming.get(fn.id) || 0) > 0) continue;
    if (roots.some((r) => r.fn.id === fn.id)) continue;
    const changed = reachableChanged(fn);
    if (changed.size) candidates.push({fn, score: changed.size, why: `reaches ${changed.size} changed function${changed.size > 1 ? 's' : ''}`});
  }
  candidates.sort((a, b) => b.score - a.score || a.fn.id.localeCompare(b.fn.id));
  const covered = new Set();
  for (const root of roots) for (const id of reachableChanged(root.fn)) covered.add(id);
  for (const candidate of candidates) {
    if (roots.length >= cfg.maxFlows) break;
    const changed = reachableChanged(candidate.fn);
    const novel = [...changed].filter((id) => !covered.has(id));
    if (!novel.length) continue;
    for (const id of changed) covered.add(id);
    candidate.why += `, ${novel.length} not reached by the other flows`;
    roots.push(candidate);
  }

  const flows = [];
  for (const root of roots) {
    const participants = new Map();
    const alias = (file) => {
      if (!participants.has(file)) participants.set(file, `p${participants.size}`);
      return participants.get(file);
    };
    const usedExternals = new Set();
    let steps = 0;
    const expanded = new Set();
    const walk = (fn, depth, trail) => {
      const out = [];
      if (depth > cfg.depth) return successors(fn).length ? ['__DEPTH__'] : [];
      for (const step of successors(fn)) {
        if (steps > 160) break;
        const resolvedFns = step.resolved.filter((r) => r.kind === 'fn');
        const ports = step.resolved.filter((r) => r.kind === 'port');
        for (const e of step.resolved.filter((r) => r.kind === 'external')) {
          steps++;
          const ext = EXTERNAL_TARGETS.find((x) => x.id === e.ext);
          usedExternals.add(ext.id);
          if (ext.kind === 'http') {
            out.push(`${alias(fn.file)}->>${extAlias(ext.id)}: ${mm(e.label)} ${mm(step.call.args || '')}`);
            out.push(`${extAlias(ext.id)}-->>${alias(fn.file)}: response`);
          } else {
            out.push(`${alias(fn.file)}->>${extAlias(ext.id)}: ${mm(e.label)}(${mm(step.call.args || '')})`);
          }
        }
        for (const p of ports) {
          steps++;
          const portFile = p.target.port.ifaceFile;
          const portKey = `${portFile}#${p.target.port.ifaceName}.${p.target.port.member}`;
          const again = expanded.has(portKey);
          out.push(`${alias(fn.file)}->>${alias(portFile)}: «port» ${mm(p.target.port.ifaceName)}.${mm(p.target.port.member)}(${mm(step.call.args)})${again ? ' ↺' : ''}`);
          if (p.impls.length && !again) {
            expanded.add(portKey);
            const several = p.impls.length > 1;
            p.impls.forEach((impl, index) => {
              if (several) out.push(`${index === 0 ? 'alt' : 'else'} ${mm(impl.impl.via)} → ${mm(impl.fn.key)}`);
              out.push(`${alias(portFile)}->>${alias(impl.fn.file)}: ${impl.fn.changed ? '✎ ' : ''}${mm(impl.fn.key)}(${mm(impl.fn.params.join(', '))})`);
              if (!trail.has(impl.fn.id) && !impl.hub) out.push(...walk(impl.fn, depth + 1, new Set([...trail, impl.fn.id])).filter((l) => l !== '__DEPTH__'));
            });
            if (several) out.push('end');
          }
        }
        const branches = resolvedFns.filter((r) => r.fn.id !== fn.id);
        const emitCall = (r) => {
          const again = expanded.has(r.fn.id);
          let body = trail.has(r.fn.id) || r.hub || again ? [] : walk(r.fn, depth + 1, new Set([...trail, r.fn.id]));
          const sameFile = r.fn.file === fn.file;
          const truncated = body.includes('__DEPTH__');
          body = body.filter((line) => line !== '__DEPTH__');
          if (truncated && !sameFile) body.push(`Note right of ${alias(r.fn.file)}: ⋯ deeper calls omitted (depth ${cfg.depth})`);
          const label = `${r.fn.changed ? '✎ ' : ''}${mm(r.declared ? r.declared + ' → ' : '')}${mm(r.fn.key)}(${mm(r.fn.params.join(', '))})${r.hub ? ' ⋯' : ''}${again ? ' ↺' : ''}`;
          if (sameFile && (again || !body.length)) return [];
          if (body.length) expanded.add(r.fn.id);
          steps++;
          return [`${alias(fn.file)}${r.declared ? '-)' : '->>'}${alias(r.fn.file)}: ${label}`, ...body];
        };
        if (branches.length > 1 && cfg.focus.length) {
          const focused = branches.filter((r) => cfg.focus.some((term) => (r.fn.file + '#' + r.fn.key).toLowerCase().includes(term.toLowerCase())));
          if (focused.length && focused.length < branches.length) {
            const omitted = branches.filter((r) => !focused.includes(r)).map((r) => r.fn.key);
            out.push(`Note over ${alias(fn.file)}: focus omitted ${mm(omitted.join(', '))}`);
            branches.splice(0, branches.length, ...focused);
          }
        }
        if (branches.length > 1) {
          const rendered = branches.map((r) => ({r, lines: emitCall(r)})).filter((b) => b.lines.length);
          if (rendered.length > 1) {
            rendered.forEach((b, index) => {
              out.push(`${index === 0 ? 'alt' : 'else'} ${mm(b.r.fn.key)}`);
              out.push(...b.lines);
            });
            out.push('end');
          } else if (rendered.length === 1) out.push(...rendered[0].lines);
        } else if (branches.length === 1) {
          out.push(...emitCall(branches[0]));
        }
      }
      return out;
    };
    alias(root.fn.file);
    const lines = walk(root.fn, 0, new Set([root.fn.id])).filter((l) => l !== '__DEPTH__');
    if (!lines.length) continue;

    const header = ['sequenceDiagram', 'autonumber'];
    const files = [...participants.keys()];
    const labels = new Map();
    for (const file of files) {
      // the shortest path suffix no other participant shares
      const segments = file.split('/');
      let label = displayLabel(file);
      for (let k = 1; k <= segments.length; k++) {
        const candidate = segments.slice(-k).join('/');
        if (!files.some((other) => other !== file && other.split('/').slice(-k).join('/') === candidate)) {
          label = k === 1 ? displayLabel(file) : candidate;
          break;
        }
      }
      labels.set(file, label);
    }
    const byPkg = new Map();
    for (const [file, a] of participants) {
      const pkg = pkgOf(file);
      if (!byPkg.has(pkg)) byPkg.set(pkg, []);
      byPkg.get(pkg).push(`participant ${a} as ${mm(labels.get(file))}`);
    }
    let paletteIndex = 0;
    for (const [pkg, decls] of byPkg) {
      header.push(`box ${BOX_PALETTE[paletteIndex++ % BOX_PALETTE.length]} ${pkg}`);
      header.push(...decls.map((d) => '  ' + d));
      header.push('end');
    }
    if (usedExternals.size) {
      header.push('box rgba(120,120,120,0.10) boundary');
      for (const ext of EXTERNAL_TARGETS.filter((e) => usedExternals.has(e.id))) header.push(`  participant ${extAlias(ext.id)} as ${mm(ext.label)}`);
      header.push('end');
    }
    flows.push({
      id: root.fn.id,
      label: `${shortName(root.fn.file)} · ${root.fn.key}`,
      why: root.why,
      mermaid: [...header, ...lines].join('\n'),
    });
  }
  return flows;
}

const BOX_PALETTE = ['rgba(74,91,208,0.10)', 'rgba(15,123,132,0.10)', 'rgba(138,74,133,0.10)', 'rgba(106,122,28,0.12)', 'rgba(200,120,30,0.10)'];

function mm(text) {
  return String(text || '')
    .replace(/[;\n\r]/g, ' ')
    .replace(/#/g, '#35;')
    .replace(/</g, '‹')
    .replace(/>/g, '›')
    .replace(/"/g, "'")
    .slice(0, 110);
}

// ---------------------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------------------

function main() {
  const started = Date.now();
  const delta = cfg.delta.filter((f) => inWorkspace(f) && isSource(f));
  const deltaSources = delta.filter((f) => !isTest(f));
  const seeds = [...new Set([...deltaSources, ...cfg.seeds])].filter((f) => fs.existsSync(path.join(REPO, f)));
  if (!seeds.length) throw new Error('no TypeScript source files in the delta and no seed given');

  const ranges = {};
  for (const file of deltaSources) ranges[file] = changedLineRanges(file);

  const scopePackages = new Set([...seeds.map(pkgOf), ...cfg.scopePackages]);
  const scopeFiles = listSourceFiles([...scopePackages]);
  const program = createProgram(scopeFiles);
  const sfByRel = new Map();
  for (const sf of program.getSourceFiles()) {
    const rel = relOf(sf.fileName);
    if (inWorkspace(rel) && !sf.isDeclarationFile) sfByRel.set(rel, sf);
  }
  console.error(`[arch-lens:ts] program: ${sfByRel.size} workspace files in ${[...scopePackages].join(', ')} (${((Date.now() - started) / 1000).toFixed(1)}s)`);

  const extractor = new Extractor(program, ranges);
  const graph = buildGraph(extractor, seeds, deltaSources, sfByRel);
  const flows = buildFlows(extractor, graph, seeds);

  const contracts = {};
  const functionsByFile = {};
  for (const node of graph.nodes) {
    const sf = sfByRel.get(node.id);
    if (sf) contracts[node.id] = extractor.exportsOf(sf);
  }
  for (const fn of extractor.functions.values()) {
    if (!graph.nodes.some((n) => n.id === fn.file)) continue;
    (functionsByFile[fn.file] = functionsByFile[fn.file] || []).push({key: fn.key, changed: fn.changed, exported: fn.exported, startLine: fn.startLine, endLine: fn.endLine, params: fn.params});
  }
  const nodes = graph.nodes.map((n) => ({...n, changed: Boolean(ranges[n.id] && ranges[n.id].length), inDelta: deltaSources.includes(n.id)}));
  const out = {nodes, edges: graph.edges, flows, contracts, functionsByFile, collapsedCallers: graph.collapsedCallers, hubs: graph.hubs};
  fs.writeFileSync(cfg.out, JSON.stringify(out));
  console.error(`[arch-lens:ts] ${nodes.length} nodes, ${graph.edges.length} edges, ${flows.length} flows in ${((Date.now() - started) / 1000).toFixed(1)}s`);
}

try {
  main();
} catch (error) {
  console.error(error.stack || String(error));
  process.exit(1);
}
