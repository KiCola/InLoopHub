/**
 * 把内容目录"接"进 vault，让 Obsidian 把文章当普通笔记。
 *
 * ## 解决什么问题
 *
 * 内容与工具解耦之后，文章通常在 vault **之外**（另一个盘、另一个目录）。
 * 这样 Obsidian 打不开它们——它只认 vault 内的文件，插件只能提示
 * "请手动打开"，体验割裂。
 *
 * 用**目录联接**把内容目录挂到 vault 里，Obsidian 就会把它当普通文件夹：
 * 文件树能看到、能点开编辑、实时预览照常工作。
 * 而文件**实际仍在原处**（联接不是拷贝），不占双份空间、也不会让坚果云
 * 同步一份 DSH 工具仓库的内容。
 *
 * 实测确认：Obsidian 会索引联接里的文件（`workspace.json` 的 `lastOpenFiles`
 * 里出现过 `InLoopContent/2026/001-.../index.md`）。
 *
 * ## 用法
 *
 *     node scripts/link-content.mjs --content "E:/InLoopHub/content"
 *     node scripts/link-content.mjs --content "..." --name MyArticles
 *     node scripts/link-content.mjs --remove
 *
 * vault 路径的解析与 link-vault.mjs 一致（参数 > 环境变量 > vault.json）。
 */

import { existsSync, lstatSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** vault 里的挂载点名。取一个明确的名字，避免与真目录混淆。 */
const DEFAULT_LINK_NAME = "InLoopContent";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const configPath = join(root, "vault.json");
const args = process.argv.slice(2);
const remove = args.includes("--remove");

function argValue(name) {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : undefined;
}

function resolveVaultPath() {
  const fromArg = argValue("--vault");
  if (fromArg) return resolve(fromArg);

  const fromEnv = process.env.INLOOP_VAULT;
  if (fromEnv && fromEnv.trim()) return resolve(fromEnv.trim());

  if (existsSync(configPath)) {
    const config = JSON.parse(readFileSync(configPath, "utf8"));
    if (typeof config.vault === "string" && config.vault.trim()) {
      return resolve(config.vault.trim());
    }
  }
  console.error("✗ 没有找到 vault 路径。");
  console.error('  用 --vault "C:/path/to/vault"，或先运行 npm run install-to-vault。');
  process.exit(1);
}

const vault = resolveVaultPath();
const linkName = argValue("--name") ?? DEFAULT_LINK_NAME;
const linkPath = join(vault, linkName);

if (!existsSync(join(vault, ".obsidian"))) {
  console.error(`✗ 这个目录不像 Obsidian vault（缺少 .obsidian）：${vault}`);
  process.exit(1);
}

if (remove) {
  if (!existsSync(linkPath)) {
    console.log(`无需移除：${linkPath} 不存在`);
    process.exit(0);
  }
  // 用 cmd 的 rmdir 删联接：它只删链接本身，不会递归删除目标内容。
  execFileSync("cmd", ["/c", "rmdir", linkPath], { stdio: "inherit" });
  console.log(`✓ 已移除联接：${linkPath}`);
  console.log("  注意：文章文件仍在原处，没有被删除。");
  process.exit(0);
}

const contentArg = argValue("--content") ?? process.env.INLOOP_CONTENT;
if (!contentArg || !contentArg.trim()) {
  console.error("✗ 没有指定内容目录。");
  console.error('  用 --content "E:/InLoopHub/content"，或设置环境变量 INLOOP_CONTENT。');
  process.exit(1);
}
const content = resolve(contentArg.trim());
if (!existsSync(content)) {
  console.error(`✗ 内容目录不存在：${content}`);
  console.error("  修正方法：先用 `inloop new` 建一篇，目录会自动创建。");
  process.exit(1);
}

if (existsSync(linkPath)) {
  const stat = lstatSync(linkPath);
  const isLink = stat.isSymbolicLink() || stat.isDirectory();
  console.log(`${linkPath} 已存在，先移除再重建。`);
  console.log(`  （它是指向别处的联接吗：${isLink ? "是或无法区分" : "否"}）`);
  execFileSync("cmd", ["/c", "rmdir", linkPath], { stdio: "inherit" });
}

// mklink /J 建的是目录联接。比 /D（符号链接）可靠：
// 符号链接在 Windows 上通常需要开发者模式或管理员权限，联接不需要。
execFileSync("cmd", ["/c", "mklink", "/J", linkPath, content], { stdio: "inherit" });

console.log("");
console.log(`✓ 已把内容目录接进 vault：`);
console.log(`    vault 内路径：${linkPath}`);
console.log(`    实际位置：   ${content}`);
console.log("");
console.log("接下来：");
console.log(`  1. 把插件的「内容目录」设为：${linkPath.replace(/\\/g, "/")}`);
console.log("  2. 在 Obsidian 里刷新文件树（或重启）——应该能看到文章了");
console.log("  3. 文章可以像普通笔记一样点开编辑；改完「构建并复制」即可");
console.log("");
console.log("说明：联接不是拷贝，文件仍在原处；删掉联接不会删文章。");
