import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { copyFile, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { dialog } from "electron";
import extract from "extract-zip";
import {
  type DesktopPlatform,
  type InstalledModelPackage,
  type ModelPackageManifest,
  type PackageHealth,
} from "../shared/types";

type RunResult = {
  code: number | null;
  stdout: string;
  stderr: string;
};

export type PackagePaths = {
  userData: string;
  homeDir: string;
  logsDir: string;
};

export type PackageRuntimeOptions = {
  platform: DesktopPlatform;
  arch: string;
  wslDistro?: string;
};

function nowIso(): string {
  return new Date().toISOString();
}

function ensureDir(dir: string): string {
  mkdirSync(dir, { recursive: true });
  return dir;
}

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]/g, "-");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function validateManifest(raw: unknown): ModelPackageManifest {
  if (!isRecord(raw)) throw new Error("opentalking.package.json must be an object");
  const requiredStrings = ["id", "title", "version", "model", "backend"] as const;
  for (const key of requiredStrings) {
    if (typeof raw[key] !== "string" || !(raw[key] as string).trim()) {
      throw new Error(`Package manifest missing string field: ${key}`);
    }
  }
  if (raw.schemaVersion !== 1) throw new Error("Package manifest schemaVersion must be 1");
  if (!Array.isArray(raw.platforms)) throw new Error("Package manifest platforms must be an array");
  if (!isRecord(raw.entry)) throw new Error("Package manifest entry must be an object");
  if (typeof raw.entry.start !== "string" || typeof raw.entry.stop !== "string") {
    throw new Error("Package manifest entry.start and entry.stop are required");
  }
  if (!isRecord(raw.health) || typeof raw.health.expectModel !== "string") {
    throw new Error("Package manifest health.expectModel is required");
  }
  if (!isRecord(raw.env)) throw new Error("Package manifest env must be an object");
  if (!isRecord(raw.resources) || !Array.isArray(raw.resources.requiredFiles)) {
    throw new Error("Package manifest resources.requiredFiles must be an array");
  }
  for (const item of raw.resources.requiredFiles) {
    if (typeof item !== "string" || !item.trim()) throw new Error("resources.requiredFiles must contain strings");
  }
  return raw as ModelPackageManifest;
}

function resolveInside(root: string, rel: string): string {
  if (path.isAbsolute(rel)) throw new Error(`Package path must be relative: ${rel}`);
  const resolved = path.resolve(root, rel);
  const safeRoot = path.resolve(root);
  if (resolved !== safeRoot && !resolved.startsWith(`${safeRoot}${path.sep}`)) {
    throw new Error(`Package path escapes install root: ${rel}`);
  }
  return resolved;
}

async function runCommand(
  command: string,
  args: string[],
  options: { cwd?: string; env?: NodeJS.ProcessEnv; timeoutMs?: number } = {},
): Promise<RunResult> {
  const timeoutMs = options.timeoutMs ?? 120_000;
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env ?? process.env,
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`Command timed out: ${command} ${args.join(" ")}`));
    }, timeoutMs);
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
  });
}

function firstSupportedPlatform(manifest: ModelPackageManifest, options: PackageRuntimeOptions) {
  return manifest.platforms.find((item) => {
    if (item.os !== options.platform) return false;
    if (item.arch) {
      const allowed = Array.isArray(item.arch) ? item.arch : [item.arch];
      if (!allowed.includes(options.arch)) return false;
    }
    return true;
  });
}

function packageHealth(
  installPath: string | undefined,
  manifest: ModelPackageManifest,
  options: PackageRuntimeOptions,
): { health: PackageHealth; reason: string | null } {
  if (!installPath || !existsSync(installPath)) return { health: "missing", reason: "模型启动包文件不存在" };
  const platform = firstSupportedPlatform(manifest, options);
  if (!platform) return { health: "unsupported", reason: `当前平台 ${options.platform}/${options.arch} 不在启动包支持列表中` };
  if (platform.supported === false) return { health: "unsupported", reason: platform.message ?? "当前平台暂不支持本地运行" };
  for (const rel of manifest.resources.requiredFiles) {
    const target = resolveInside(installPath, rel);
    if (!existsSync(target)) return { health: "missing", reason: `缺少文件：${rel}` };
  }
  return { health: "compatible", reason: null };
}

function quoteForBash(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

function joinRuntimePath(root: string, ...parts: string[]): string {
  return root.startsWith("/") ? path.posix.join(root, ...parts) : path.join(root, ...parts);
}

function envExportsForBash(env: NodeJS.ProcessEnv): string {
  const keys = [
    "OPENTALKING_DEFAULT_MODEL",
    "OPENTALKING_QUICKTALK_BACKEND",
    "OPENTALKING_API_PORT",
    "OPENTALKING_PACKAGE_ROOT",
    "OPENTALKING_QUICKTALK_ASSET_ROOT",
    "OPENTALKING_FFMPEG_BIN",
  ];
  const exports: string[] = [];
  for (const key of keys) {
    const value = env[key];
    if (value) exports.push(`export ${key}=${quoteForBash(value)}`);
  }
  return exports.join(" && ");
}

export function buildPackageEnv(
  manifest: ModelPackageManifest,
  packageRoot: string,
  apiPort: number,
  ffmpegBin: string | null,
): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    OPENTALKING_DEFAULT_MODEL: manifest.model,
    OPENTALKING_QUICKTALK_BACKEND: manifest.model === "quicktalk" ? manifest.backend : undefined,
    OPENTALKING_API_PORT: String(apiPort),
    OPENTALKING_PACKAGE_ROOT: packageRoot,
  };
  for (const [key, value] of Object.entries(manifest.env)) {
    env[key] = value
      .replaceAll("${PACKAGE_ROOT}", packageRoot)
      .replaceAll("${API_PORT}", String(apiPort))
      .replaceAll("${FFMPEG_BIN}", ffmpegBin ?? "ffmpeg");
  }
  if (manifest.model === "quicktalk" && !env.OPENTALKING_QUICKTALK_ASSET_ROOT) {
    env.OPENTALKING_QUICKTALK_ASSET_ROOT = joinRuntimePath(packageRoot, "models", "quicktalk");
  }
  if (ffmpegBin) {
    env.OPENTALKING_FFMPEG_BIN = ffmpegBin;
    env.PATH = `${path.dirname(ffmpegBin)}${path.delimiter}${env.PATH ?? ""}`;
  }
  return env;
}

export class ModelPackageStore {
  private readonly filePath: string;
  private readonly packagesDir: string;

  constructor(private readonly paths: PackagePaths, private readonly runtime: PackageRuntimeOptions) {
    this.filePath = path.join(paths.userData, "model-packages.json");
    this.packagesDir = ensureDir(path.join(paths.homeDir, "packages"));
  }

  async list(): Promise<InstalledModelPackage[]> {
    const packages = await this.readPackages();
    return packages.map((item) => this.withHealth(item));
  }

  async get(id: string): Promise<InstalledModelPackage | null> {
    const packages = await this.list();
    return packages.find((item) => item.id === id) ?? null;
  }

  async importPackage(inputPath?: string): Promise<InstalledModelPackage> {
    const filePath = inputPath ?? (await this.pickPackageFile());
    if (!filePath) throw new Error("未选择模型启动包");
    if (!existsSync(filePath) || !statSync(filePath).isFile()) throw new Error(`模型启动包不存在：${filePath}`);

    const tempRoot = ensureDir(path.join(os.tmpdir(), `opentalking-otpkg-${Date.now()}`));
    try {
      await this.extractPackage(filePath, tempRoot);
      const manifestPath = path.join(tempRoot, "opentalking.package.json");
      if (!existsSync(manifestPath)) throw new Error("模型启动包缺少 opentalking.package.json");
      const manifest = validateManifest(JSON.parse(await readFile(manifestPath, "utf-8")));
      const installPath = path.join(this.packagesDir, `${safeId(manifest.id)}-${safeId(manifest.version)}`);
      const wslInstallPath = this.defaultWslInstallPath(manifest);
      rmSync(installPath, { recursive: true, force: true });
      await this.copyDirectory(tempRoot, installPath);
      if (this.runtime.platform === "win32") {
        await this.mirrorPackageToWsl(installPath, wslInstallPath);
      }
      const packages = (await this.readPackages()).filter((item) => item.id !== manifest.id);
      const record: InstalledModelPackage = this.withHealth({
        id: manifest.id,
        title: manifest.title,
        version: manifest.version,
        model: manifest.model,
        backend: manifest.backend,
        manifest,
        installPath,
        wslInstallPath,
        logPath: path.join(this.paths.logsDir, `${safeId(manifest.id)}.log`),
        health: "compatible",
        healthReason: null,
        installedAt: nowIso(),
        updatedAt: nowIso(),
      });
      packages.push(record);
      await this.writePackages(packages);
      return record;
    } finally {
      rmSync(tempRoot, { recursive: true, force: true });
    }
  }

  async deletePackage(id: string): Promise<void> {
    const packages = await this.readPackages();
    const target = packages.find((item) => item.id === id);
    if (target?.installPath) rmSync(target.installPath, { recursive: true, force: true });
    if (this.runtime.platform === "win32" && target?.wslInstallPath) {
      await this.deleteWslPath(target.wslInstallPath).catch(() => null);
    }
    await this.writePackages(packages.filter((item) => item.id !== id));
  }

  async tailLogs(id: string, lines = 80): Promise<string> {
    const pkg = await this.get(id);
    if (!pkg) return `Package not found: ${id}`;
    if (this.runtime.platform === "win32" && pkg.wslInstallPath) {
      const distro = this.runtime.wslDistro ?? "Ubuntu-22.04";
      const command = `tail -n ${Math.max(1, Math.min(lines, 500))} ${quoteForBash(`${pkg.wslInstallPath}/logs/opentalking-package.log`)} ${quoteForBash(`${pkg.wslInstallPath}/logs/start.log`)} 2>/dev/null || true`;
      const result = await runCommand("wsl.exe", ["-d", distro, "--", "bash", "-lc", command], { timeoutMs: 20_000 });
      return result.stdout || result.stderr || `No WSL package log output: ${pkg.wslInstallPath}`;
    }
    if (!pkg.logPath || !existsSync(pkg.logPath)) return `Log file not found: ${pkg.logPath ?? ""}`;
    return readFileSync(pkg.logPath, "utf-8").split(/\r?\n/).slice(-Math.max(1, Math.min(lines, 500))).join("\n");
  }

  buildNativeCommand(
    pkg: InstalledModelPackage,
    action: "start" | "stop",
  ): { command: string; args: string[]; cwd: string } {
    if (!pkg.installPath) throw new Error("Package installPath missing");
    const rel = action === "start" ? pkg.manifest.entry.start : pkg.manifest.entry.stop;
    const script = resolveInside(pkg.installPath, rel);
    const cwd = resolveInside(pkg.installPath, pkg.manifest.entry.cwd ?? ".");
    return { command: "bash", args: [script], cwd };
  }

  buildWslCommand(
    pkg: InstalledModelPackage,
    action: "start" | "stop",
    distro: string,
    env?: NodeJS.ProcessEnv,
  ): { command: string; args: string[] } {
    const root = pkg.wslInstallPath || this.defaultWslInstallPath(pkg.manifest);
    const rel = action === "start" ? pkg.manifest.entry.start : pkg.manifest.entry.stop;
    const cwd = pkg.manifest.entry.cwd ? `${root}/${pkg.manifest.entry.cwd}` : root;
    const exports = env ? envExportsForBash(env) : "";
    const command = [exports, `cd ${quoteForBash(cwd)}`, `bash ${quoteForBash(`${root}/${rel}`)}`].filter(Boolean).join(" && ");
    return { command: "wsl.exe", args: ["-d", distro, "--", "bash", "-lc", command] };
  }

  packageRootForRuntime(pkg: InstalledModelPackage): string {
    if (this.runtime.platform === "win32") return pkg.wslInstallPath || this.defaultWslInstallPath(pkg.manifest);
    if (!pkg.installPath) throw new Error("Package installPath missing");
    return pkg.installPath;
  }

  private withHealth(pkg: InstalledModelPackage): InstalledModelPackage {
    const { health, reason } = packageHealth(pkg.installPath, pkg.manifest, this.runtime);
    return { ...pkg, health, healthReason: reason };
  }

  private async pickPackageFile(): Promise<string | undefined> {
    const result = await dialog.showOpenDialog({
      title: "选择 OpenTalking 模型启动包",
      properties: ["openFile"],
      filters: [
        { name: "OpenTalking Package", extensions: ["otpkg", "zip"] },
        { name: "All Files", extensions: ["*"] },
      ],
    });
    return result.canceled ? undefined : result.filePaths[0];
  }

  private async extractPackage(filePath: string, targetDir: string): Promise<void> {
    const extension = path.extname(filePath).toLowerCase();
    if (extension !== ".otpkg" && extension !== ".zip") {
      throw new Error("模型启动包必须是 .otpkg 或 .zip 文件");
    }
    await extract(filePath, { dir: targetDir });
  }

  private async copyDirectory(from: string, to: string) {
    const fs = await import("node:fs/promises");
    ensureDir(to);
    for (const entry of await fs.readdir(from, { withFileTypes: true })) {
      const source = path.join(from, entry.name);
      const target = path.join(to, entry.name);
      if (entry.isDirectory()) {
        await this.copyDirectory(source, target);
      } else if (entry.isFile()) {
        await copyFile(source, target);
      }
    }
  }

  private defaultWslInstallPath(manifest: ModelPackageManifest): string {
    return `/home/opentalking/.opentalking/packages/${safeId(manifest.id)}-${safeId(manifest.version)}`;
  }

  private async mirrorPackageToWsl(installPath: string, wslInstallPath: string) {
    const distro = this.runtime.wslDistro ?? "Ubuntu-22.04";
    const converted = await runCommand("wsl.exe", ["-d", distro, "--", "wslpath", "-a", installPath], { timeoutMs: 20_000 });
    const wslSource = converted.stdout.trim();
    if (!wslSource) throw new Error(`无法转换 Windows 包路径到 WSL：${installPath}`);
    const command = [
      `rm -rf ${quoteForBash(wslInstallPath)}`,
      `mkdir -p ${quoteForBash(path.posix.dirname(wslInstallPath))}`,
      `mkdir -p ${quoteForBash(wslInstallPath)}`,
      `cp -a ${quoteForBash(`${wslSource}/.`)} ${quoteForBash(`${wslInstallPath}/`)}`,
    ].join(" && ");
    const result = await runCommand("wsl.exe", ["-d", distro, "--", "bash", "-lc", command], { timeoutMs: 300_000 });
    if (result.code !== 0) {
      throw new Error(result.stderr || result.stdout || "WSL 模型包导入失败");
    }
  }

  private async deleteWslPath(wslPath: string) {
    const distro = this.runtime.wslDistro ?? "Ubuntu-22.04";
    await runCommand("wsl.exe", ["-d", distro, "--", "bash", "-lc", `rm -rf ${quoteForBash(wslPath)}`], { timeoutMs: 30_000 });
  }

  private async readPackages(): Promise<InstalledModelPackage[]> {
    if (!existsSync(this.filePath)) return [];
    const parsed = JSON.parse(await readFile(this.filePath, "utf-8")) as { packages?: InstalledModelPackage[] };
    return Array.isArray(parsed.packages) ? parsed.packages : [];
  }

  private async writePackages(packages: InstalledModelPackage[]) {
    ensureDir(this.paths.userData);
    await writeFile(this.filePath, `${JSON.stringify({ packages }, null, 2)}\n`, "utf-8");
  }
}
