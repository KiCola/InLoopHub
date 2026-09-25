/**
 * 插件构建脚本。
 *
 * 产出 `dist/`：`main.js` 与 `manifest.json`——**这两个文件就是插件的全部**。
 * Obsidian 从插件目录读取它们，不需要 `package.json` 与 `node_modules`。
 *
 * 为什么把产物单独放 `dist/` 而不是直接写进 vault：
 * vault 位于坚果云同步目录，把构建中间物同步到云端既慢又无意义。
 * 部署是单独一步（`--deploy` 或 npm run deploy），只把两个终态文件拷过去。
 */

import esbuild from "esbuild";
import { builtinModules } from "module";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const root = dirname(fileURLToPath(import.meta.url));
const distDir = join(root, "dist");
const watch = process.argv.includes("--watch");

/** 从 package.json 与 manifest.json 生成最终清单，避免版本号两处维护 */
function buildManifest() {
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  const manifest = JSON.parse(readFileSync(join(root, "manifest.json"), "utf8"));
  manifest.version = pkg.version;
  return manifest;
}

const buildOptions = {
  entryPoints: [join(root, "src/main.ts")],
  outfile: join(distDir, "main.js"),
  bundle: true,
  // Obsidian 与 Electron 已经提供这些模块，不能打进产物
  external: [
    "obsidian",
    "electron",
    "@codemirror/*",
    "@lezer/*",
    ...builtinModules,
    ...builtinModules.map((m) => `node:${m}`),
  ],
  format: "cjs",
  target: "es2022",
  platform: "node",
  logLevel: "info",
  sourcemap: "inline",
  treeShaking: true,
};

if (watch) {
  const ctx = await esbuild.context(buildOptions);
  await ctx.watch();
  console.log("watching...");
} else {
  mkdirSync(distDir, { recursive: true });
  await esbuild.build(buildOptions);
  writeFileSync(
    join(distDir, "manifest.json"),
    JSON.stringify(buildManifest(), null, 2) + "\n",
    "utf8",
  );
  copyFileSync(join(root, "README.md"), join(distDir, "README.md"));
  console.log(`built -> ${distDir}`);
}
