/**
 * 把插件挂到 Obsidian vault 的插件目录。
 *
 * 用**目录联接**（Windows junction）而不是拷贝：改动源码后重新构建即可生效，
 * 不需要每次手工复制。vault 里只多一个链接，坚果云不会同步插件源码与
 * `node_modules`。
 *
 * 用法：
 *     node scripts/link-vault.mjs                      # 读取本地配置
 *     node scripts/link-vault.mjs --vault "C:/path/to/vault"
 *     node scripts/link-vault.mjs --remove             # 移除链接（不动 dist）
 *
 * 配置来源按优先级：
 *     1. 命令行 --vault <路径>
 *     2. 环境变量 INLOOP_VAULT
 *     3. plugin/vault.json（本机配置，**不入 Git**）
 *
 * 为什么把 vault 路径放在被忽略的本地文件里：它是每个人机器上不同的绝对路径，
 * 提交进仓库既没用又泄漏目录结构（AGENTS.md §4）。
 */

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** 插件在 vault 中的目录名（会显示为 .obsidian/plugins/<这个名字>） */
const PLUGIN_ID = "inloop-notes";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distDir = join(root, "dist");
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
  console.error("  请任选一种方式提供：");
  console.error('    1. node scripts/link-vault.mjs --vault "C:/path/to/vault"');
  console.error("    2. 设置环境变量 INLOOP_VAULT");
  console.error(`    3. 创建 ${configPath}，内容形如 {"vault": "C:/path/to/vault"}`);
  process.exit(1);
}

const vault = resolveVaultPath();
const pluginsDir = join(vault, ".obsidian", "plugins");
const linkPath = join(pluginsDir, PLUGIN_ID);

if (!existsSync(vault)) {
  console.error(`✗ vault 目录不存在：${vault}`);
  process.exit(1);
}
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
  // PowerShell 的 Remove-Item 在非交互模式下可能就链接弹确认提示。
  execFileSync("cmd", ["/c", "rmdir", linkPath], { stdio: "inherit" });
  console.log(`✓ 已移除链接：${linkPath}`);
  process.exit(0);
}

if (!existsSync(distDir)) {
  console.error(`✗ 还没有构建产物：${distDir}`);
  console.error("  修正方法：先运行 npm run build");
  process.exit(1);
}

mkdirSync(pluginsDir, { recursive: true });

if (existsSync(linkPath)) {
  console.log(`链接已存在，先移除：${linkPath}`);
  execFileSync("cmd", ["/c", "rmdir", linkPath], { stdio: "inherit" });
}

// 记下 vault 路径，下次不必再传
writeFileSync(configPath, JSON.stringify({ vault }, null, 2) + "\n", "utf8");

// 用 mklink /J 创建目录联接。比 mklink /D（符号链接）可靠：
// 符号链接在 Windows 上通常需要开发者模式或管理员权限，联接不需要。
execFileSync("cmd", ["/c", "mklink", "/J", linkPath, distDir], { stdio: "inherit" });

console.log("");
console.log(`✓ 插件已挂到 vault：${linkPath}`);
console.log(`  → 指向：${distDir}`);
console.log("");
console.log("接下来在 Obsidian 里：设置 → 第三方插件 → 刷新 → 启用「InLoop 手记」");
console.log("（首次需要在「已安装插件」里打开开关；若列表里看不到，重启 Obsidian）");
