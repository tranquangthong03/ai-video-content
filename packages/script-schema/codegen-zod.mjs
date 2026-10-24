// Generates Zod schemas + inferred types, and the LAYOUTS_BY_TYPE tables, from schemas/*.json.
// Usage: node codegen-zod.mjs --py-layouts <dir> <outDir>[=<import-ext>] ...
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { jsonSchemaToZod, parseSchema } from "json-schema-to-zod";

const here = dirname(fileURLToPath(import.meta.url));
const schemaDir = join(here, "schemas");

const args = process.argv.slice(2);
const pyIdx = args.indexOf("--py-layouts");
const pyDir = pyIdx >= 0 ? resolve(args.splice(pyIdx, 2)[1]) : null;
// Each target is "<dir>" or "<dir>=<import-ext>" (NodeNext needs ".js" in the index re-exports)
const targets = args.map((a) => {
  const [d, ext = ""] = a.split("=");
  return { dir: resolve(d), ext };
});
if (targets.length === 0) throw new Error("usage: codegen-zod.mjs [--py-layouts dir] <outDir>...");

const HEADER = "// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.\n";
const PY_HEADER = "# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.\n";
const cache = new Map();
const load = (file) => {
  if (!cache.has(file)) cache.set(file, JSON.parse(readFileSync(join(schemaDir, file), "utf8")));
  return cache.get(file);
};

// Inline every $ref ("file.json" or "[file.json]#/$defs/X") so each schema is self-contained.
function deref(node, file) {
  if (Array.isArray(node)) return node.map((n) => deref(n, file));
  if (node === null || typeof node !== "object") return node;
  if (typeof node.$ref === "string") {
    const [refFile, pointer] = node.$ref.split("#");
    const targetFile = refFile || file;
    let target = load(targetFile);
    for (const part of (pointer ?? "").split("/").filter(Boolean)) target = target[part];
    return deref(target, targetFile);
  }
  const out = {};
  for (const [k, v] of Object.entries(node)) {
    if (["$defs", "$schema", "$id", "description"].includes(k)) continue;
    // oneOf branches are mutually exclusive here; anyOf is what the Zod converter understands
    out[k === "oneOf" ? "anyOf" : k] = deref(v, file);
  }
  return out;
}

// oneOf + discriminator -> z.discriminatedUnion (json-schema-to-zod would emit a plain union)
function parserOverride(schema, refs) {
  if (!schema.discriminator || !Array.isArray(schema.anyOf)) return undefined;
  const members = schema.anyOf.map((m, i) =>
    parseSchema(m, { ...refs, path: [...refs.path, "anyOf", i] }),
  );
  return `z.discriminatedUnion(${JSON.stringify(schema.discriminator.propertyName)}, [${members.join(", ")}])`;
}

const files = readdirSync(schemaDir).filter((f) => f.endsWith(".json")).sort();
const indexLines = [];
for (const file of files) {
  const raw = load(file);
  const name = raw.title;
  const zod = jsonSchemaToZod(deref(raw, file), {
    name: `${name}Schema`,
    module: "esm",
    type: name,
    parserOverride,
  });
  const stem = file.replace(/\.json$/, "");
  indexLines.push(`export * from "./${stem}";`);
  for (const { dir } of targets) {
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, `${stem}.ts`), `${HEADER}${zod}\n`);
  }
}

// LAYOUTS_BY_TYPE: scene type -> allowed layouts, read from the scene sub-schemas
const sceneDefs = load("scene.json").$defs;
const layouts = {};
const fields = {}; // scene type -> properties that scene type allows
for (const def of Object.values(sceneDefs)) {
  const type = def.properties?.type?.const;
  if (!type) continue;
  layouts[type] = def.properties.layout.enum;
  fields[type] = Object.keys(def.properties);
}
const tsLayouts = `${HEADER}
export const LAYOUTS_BY_TYPE = ${JSON.stringify(layouts, null, 2)} as const;

export const FIELDS_BY_TYPE = ${JSON.stringify(fields, null, 2)} as const;

export type SceneType = keyof typeof LAYOUTS_BY_TYPE;
export type LayoutOf<T extends SceneType> = (typeof LAYOUTS_BY_TYPE)[T][number];
`;
const pyLayouts = `${PY_HEADER}
LAYOUTS_BY_TYPE: dict[str, tuple[str, ...]] = {
${Object.entries(layouts)
  .map(([t, ls]) => `    ${JSON.stringify(t)}: (${ls.map((l) => JSON.stringify(l)).join(", ")}),`)
  .join("\n")}
}
`;
const pyMeta = `${PY_HEADER}
FIELDS_BY_TYPE: dict[str, tuple[str, ...]] = {
${Object.entries(fields)
  .map(([t, fs]) => `    ${JSON.stringify(t)}: (${fs.map((f) => JSON.stringify(f)).join(", ")}),`)
  .join("\n")}
}
`;
indexLines.push('export * from "./layouts";');

for (const { dir, ext } of targets) {
  writeFileSync(join(dir, "layouts.ts"), tsLayouts);
  const lines = indexLines.map((l) => l.replace(/";$/, `${ext}";`));
  writeFileSync(join(dir, "index.ts"), `${HEADER}${lines.join("\n")}\n`);
}
if (pyDir) {
  mkdirSync(pyDir, { recursive: true });
  writeFileSync(join(pyDir, "layouts.py"), pyLayouts);
  writeFileSync(join(pyDir, "scene_meta.py"), pyMeta);
}
console.log(`zod: ${files.length} schemas -> ${targets.map((t) => t.dir).join(", ")}`);
