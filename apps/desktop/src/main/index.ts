import { app, BrowserWindow, Menu, ipcMain, shell, session } from "electron";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { createServer as createNetServer } from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import httpProxy from "http-proxy";
import {
  ModelPackageStore,
  buildPackageEnv,
  type PackageRuntimeOptions,
} from "./packageManager";
import {
  DESKTOP_CHANNELS,
  type BackendMode,
  type BackendProfile,
  type DesktopPlatform,
  type DesktopStatus,
  type InstalledModelPackage,
  type OpenPathKind,
  type SaveProfileInput,
  type StartBackendOptions,
} from "../shared/types";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_API_PORT = 8010;
const MAX_API_PORT = 8099;

type RunResult = {
  code: number | null;
  stdout: string;
  stderr: string;
};

type DesktopCommand = {
  command: string;
  args: string[];
  cwd?: string;
};

function nowIso(): string {
  return new Date().toISOString();
}

function normalizeUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

function platform(): DesktopPlatform {
  if (process.platform === "darwin" || process.platform === "win32") return process.platform;
  return "linux";
}

function bashQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

function findRepoRoot(): string {
  const candidates = [
    process.env.OPENTALKING_REPO_ROOT,
    path.resolve(process.cwd(), "../.."),
    path.resolve(process.cwd()),
    path.resolve(app.getAppPath(), "../.."),
    path.resolve(app.getAppPath(), "../../.."),
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    if (
      existsSync(path.join(candidate, "scripts/quickstart/start_opentalking.sh")) &&
      existsSync(path.join(candidate, "apps/web/package.json"))
    ) {
      return candidate;
    }
  }
  return path.resolve(process.cwd(), "../..");
}

function runtimeArch(): string {
  if (process.arch === "x64") return "x64";
  if (process.arch === "arm64") return "arm64";
  return process.arch;
}

function platformResourceDirName(): string {
  const osName = process.platform === "darwin" ? "mac" : process.platform === "win32" ? "win" : "linux";
  return `${osName}-${runtimeArch()}`;
}

function extraRoot(): string {
  if (app.isPackaged) return path.join(process.resourcesPath, "extra");
  return path.resolve(app.getAppPath(), "resources", "extra");
}

function resolveExtraBinary(binary: "ffmpeg" | "ffprobe"): string | null {
  const name = process.platform === "win32" ? `${binary}.exe` : binary;
  const candidates = [
    path.join(extraRoot(), platformResourceDirName(), name),
    path.join(extraRoot(), "common", name),
  ];
  return candidates.find((candidate) => existsSync(candidate)) ?? null;
}

function ensureDir(dir: string): string {
  mkdirSync(dir, { recursive: true });
  return dir;
}

function jsonResponse(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

function contentTypeFor(filePath: string): string {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".svg")) return "image/svg+xml";
  if (filePath.endsWith(".png")) return "image/png";
  if (filePath.endsWith(".jpg") || filePath.endsWith(".jpeg")) return "image/jpeg";
  return "application/octet-stream";
}

async function isPortFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = createNetServer()
      .once("error", () => resolve(false))
      .once("listening", () => {
        server.close(() => resolve(true));
      })
      .listen(port, "127.0.0.1");
  });
}

async function choosePort(preferred = DEFAULT_API_PORT): Promise<number> {
  for (let port = preferred; port <= MAX_API_PORT; port += 1) {
    if (await isPortFree(port)) return port;
  }
  throw new Error(`No free API port in ${preferred}-${MAX_API_PORT}`);
}

async function runCommand(
  command: string,
  args: string[],
  options: { cwd?: string; env?: NodeJS.ProcessEnv; timeoutMs?: number } = {},
): Promise<RunResult> {
  const timeoutMs = options.timeoutMs ?? 75_000;
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

async function checkModels(apiBaseUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${normalizeUrl(apiBaseUrl)}/models`, { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch {
    return false;
  }
}

function firstIpv4(value: string): string | null {
  return value
    .split(/\s+/)
    .map((item) => item.trim())
    .find((item) => /^\d{1,3}(?:\.\d{1,3}){3}$/.test(item)) ?? null;
}

class ProfileStore {
  private readonly filePath: string;
  private activeProfileId: string | null = null;

  constructor(private readonly userDataDir: string, private readonly repoRoot: string) {
    this.filePath = path.join(userDataDir, "profiles.json");
  }

  async list(): Promise<BackendProfile[]> {
    const data = await this.readData();
    return data.profiles;
  }

  async active(): Promise<BackendProfile | null> {
    const data = await this.readData();
    this.activeProfileId = data.activeProfileId ?? data.profiles[0]?.id ?? null;
    return data.profiles.find((profile) => profile.id === this.activeProfileId) ?? data.profiles[0] ?? null;
  }

  async activate(id: string): Promise<BackendProfile> {
    const data = await this.readData();
    const profile = data.profiles.find((item) => item.id === id);
    if (!profile) throw new Error(`Profile not found: ${id}`);
    data.activeProfileId = id;
    this.activeProfileId = id;
    await this.writeData(data);
    return profile;
  }

  async save(input: SaveProfileInput): Promise<BackendProfile> {
    const data = await this.readData();
    const id = input.id || `${input.mode}-${Date.now()}`;
    const existing = data.profiles.find((item) => item.id === id);
    const createdAt = existing?.createdAt ?? nowIso();
    const profile: BackendProfile = {
      ...input,
      id,
      createdAt,
      updatedAt: nowIso(),
    };
    data.profiles = existing
      ? data.profiles.map((item) => (item.id === id ? profile : item))
      : [...data.profiles, profile];
    data.activeProfileId = data.activeProfileId ?? id;
    await this.writeData(data);
    return profile;
  }

  private defaults(): { activeProfileId: string; profiles: BackendProfile[] } {
    const createdAt = nowIso();
    const remoteProfile: BackendProfile = {
      id: "remote-default",
      name: "远端 OpenTalking API",
      mode: "remote",
      apiBaseUrl: `http://127.0.0.1:${DEFAULT_API_PORT}`,
      createdAt,
      updatedAt: createdAt,
    };
    const profiles: BackendProfile[] =
      platform() === "win32"
        ? [
            {
              id: "wsl-mock",
              name: "WSL2 Mock 体验",
              mode: "managed-mock",
              wslDistro: "Ubuntu-22.04",
              wslRepoPath: "/home/opentalking/opentalking",
              apiPort: DEFAULT_API_PORT,
              autoStart: false,
              createdAt,
              updatedAt: createdAt,
            },
            remoteProfile,
          ]
        : [
            {
              id: "local-mock",
              name: "本地 Mock 体验",
              mode: "managed-mock",
              repoPath: this.repoRoot,
              apiPort: DEFAULT_API_PORT,
              autoStart: false,
              createdAt,
              updatedAt: createdAt,
            },
            remoteProfile,
          ];
    return { activeProfileId: profiles[0].id, profiles };
  }

  private async readData(): Promise<{ activeProfileId: string | null; profiles: BackendProfile[] }> {
    if (!existsSync(this.filePath)) {
      const data = this.defaults();
      await this.writeData(data);
      return data;
    }
    const raw = await readFile(this.filePath, "utf-8");
    const parsed = JSON.parse(raw) as { activeProfileId?: string; profiles?: BackendProfile[] };
    const profiles = Array.isArray(parsed.profiles) && parsed.profiles.length > 0 ? parsed.profiles : this.defaults().profiles;
    return { activeProfileId: parsed.activeProfileId ?? profiles[0]?.id ?? null, profiles };
  }

  private async writeData(data: { activeProfileId?: string | null; profiles: BackendProfile[] }) {
    ensureDir(this.userDataDir);
    await writeFile(this.filePath, `${JSON.stringify(data, null, 2)}\n`, "utf-8");
  }
}

class DesktopProxy {
  private server: Server | null = null;
  private target: string | null = null;
  private port: number | null = null;
  private readonly proxy = httpProxy.createProxyServer({ changeOrigin: true, ws: true });

  constructor(private readonly webDistDir: string) {}

  async start(): Promise<string> {
    if (this.server && this.port) return this.baseUrl;
    this.server = createServer((req, res) => this.handle(req, res));
    this.server.on("upgrade", (req, socket, head) => {
      if (!this.target || !req.url?.startsWith("/api")) {
        socket.destroy();
        return;
      }
      req.url = req.url.replace(/^\/api/, "") || "/";
      this.proxy.ws(req, socket, head, { target: this.target });
    });
    await new Promise<void>((resolve) => {
      this.server?.listen(0, "127.0.0.1", () => resolve());
    });
    const address = this.server.address();
    if (!address || typeof address === "string") throw new Error("Failed to start desktop proxy");
    this.port = address.port;
    return this.baseUrl;
  }

  setTarget(apiBaseUrl: string | null) {
    this.target = apiBaseUrl ? normalizeUrl(apiBaseUrl) : null;
  }

  get apiBaseUrl(): string | null {
    return this.port ? `${this.baseUrl}/api` : null;
  }

  get webUiUrl(): string | null {
    return this.port ? `${this.baseUrl}/webui/` : null;
  }

  private get baseUrl(): string {
    return `http://127.0.0.1:${this.port}`;
  }

  private handle(req: IncomingMessage, res: ServerResponse) {
    const url = req.url ?? "/";
    if (url.startsWith("/api")) {
      if (!this.target) {
        jsonResponse(res, 503, { error: "No active OpenTalking backend profile" });
        return;
      }
      req.url = url.replace(/^\/api/, "") || "/";
      this.proxy.web(req, res, { target: this.target }, (error) => {
        jsonResponse(res, 502, { error: error.message });
      });
      return;
    }
    if (url.startsWith("/webui") || url.startsWith("/assets/")) {
      this.serveWebUi(url, res);
      return;
    }
    jsonResponse(res, 404, { error: "Not found" });
  }

  private serveWebUi(url: string, res: ServerResponse) {
    if (!existsSync(this.webDistDir)) {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end("<h1>OpenTalking WebUI build missing</h1><p>Run npm --prefix apps/web run build first.</p>");
      return;
    }
    const rel = decodeURIComponent(url.startsWith("/assets/") ? url.slice(1) : url.replace(/^\/webui\/?/, "")) || "index.html";
    const candidate = path.resolve(this.webDistDir, rel);
    const safeRoot = path.resolve(this.webDistDir);
    let filePath = candidate.startsWith(safeRoot) && existsSync(candidate) && statSync(candidate).isFile()
      ? candidate
      : path.join(safeRoot, "index.html");
    if (!existsSync(filePath)) filePath = path.join(safeRoot, "index.html");
    res.writeHead(200, { "content-type": contentTypeFor(filePath) });
    res.end(readFileSync(filePath));
  }
}

class BackendController {
  private currentProfile: BackendProfile | null = null;
  private currentPackage: InstalledModelPackage | null = null;
  private status: DesktopStatus;
  private startedByDesktop = false;

  constructor(
    private readonly store: ProfileStore,
    private readonly packageStore: ModelPackageStore,
    private readonly proxy: DesktopProxy,
    private readonly paths: { userData: string; homeDir: string; worksDir: string; logsDir: string },
  ) {
    this.status = this.blankStatus("stopped");
  }

  async init() {
    this.currentProfile = await this.store.active();
    await this.refreshStatus("stopped");
  }

  getStatus(): DesktopStatus {
    return this.status;
  }

  async activateProfile(id: string): Promise<DesktopStatus> {
    this.currentProfile = await this.store.activate(id);
    this.currentPackage = null;
    await this.refreshStatus("stopped");
    return this.status;
  }

  async start(options: StartBackendOptions = {}): Promise<DesktopStatus> {
    if (options.profileId) this.currentProfile = await this.store.activate(options.profileId);
    this.currentPackage = null;
    const profile = this.currentProfile ?? (await this.store.active());
    if (!profile) throw new Error("No backend profile configured");
    this.currentProfile = profile;
    await this.refreshStatus("starting");

    if (profile.mode === "remote") {
      const apiBaseUrl = normalizeUrl(profile.apiBaseUrl ?? "");
      if (!apiBaseUrl) throw new Error("Remote profile is missing apiBaseUrl");
      const ready = await checkModels(apiBaseUrl);
      await this.refreshStatus(ready ? "ready" : "error", ready ? null : "远端 OpenTalking API 不可达");
      return this.status;
    }

    const apiPort = options.forcePort ?? (await choosePort(profile.apiPort ?? DEFAULT_API_PORT));
    const args = this.startCommand(profile, apiPort);
    const env = this.backendEnv(profile);
    const result = await runCommand(args.command, args.args, { cwd: args.cwd, env });
    if (result.code !== 0) {
      await this.refreshStatus("error", result.stderr || result.stdout || `启动失败：exit ${result.code}`);
      return this.status;
    }
    this.startedByDesktop = true;
    const resolved = await this.resolveManagedApiBaseUrl(profile, apiPort);
    await this.refreshStatus(
      resolved.ready ? "ready" : "error",
      resolved.ready ? null : resolved.error,
      apiPort,
      resolved.apiBaseUrl,
    );
    return this.status;
  }

  async stop(): Promise<DesktopStatus> {
    if (this.currentPackage) {
      await this.stopPackageBackend(this.currentPackage.id);
      return this.status;
    }
    const profile = this.currentProfile;
    if (profile && profile.mode !== "remote") {
      const apiPort = this.status.apiPort ?? profile.apiPort ?? DEFAULT_API_PORT;
      const args = this.stopCommand(profile, apiPort);
      await runCommand(args.command, args.args, { cwd: args.cwd, timeoutMs: 30_000 }).catch(() => null);
    }
    this.startedByDesktop = false;
    await this.refreshStatus("stopped");
    return this.status;
  }

  async stopIfStartedByDesktop(): Promise<void> {
    if (this.startedByDesktop) await this.stop();
  }

  async tailLogs(lines = 80): Promise<string> {
    if (this.currentPackage) return this.packageStore.tailLogs(this.currentPackage.id, lines);
    const profile = this.currentProfile;
    const apiPort = this.status.apiPort ?? profile?.apiPort ?? DEFAULT_API_PORT;
    if (!profile) return "No active profile";
    if (process.platform === "win32" && profile.wslRepoPath) {
      const logPath = path.posix.join(path.posix.dirname(profile.wslRepoPath), "logs", `opentalking-api-${apiPort}.log`);
      const command = `tail -n ${Math.max(1, Math.min(lines, 500))} ${bashQuote(logPath)} 2>/dev/null || true`;
      const result = await runCommand("wsl.exe", ["-d", profile.wslDistro ?? "Ubuntu-22.04", "--", "bash", "-lc", command]);
      return result.stdout || result.stderr || `No WSL log output: ${logPath}`;
    }
    const logPath = this.localLogPath(profile, apiPort);
    if (!existsSync(logPath)) return `Log file not found: ${logPath}`;
    return readFileSync(logPath, "utf-8").split(/\r?\n/).slice(-lines).join("\n");
  }

  async startPackageBackend(packageId: string, options: StartBackendOptions = {}): Promise<DesktopStatus> {
    const pkg = await this.packageStore.get(packageId);
    if (!pkg) throw new Error(`模型启动包不存在：${packageId}`);
    this.currentPackage = pkg;
    this.currentProfile = {
      id: `package:${pkg.id}`,
      name: pkg.title,
      mode: "managed-package",
      apiPort: options.forcePort ?? DEFAULT_API_PORT,
      autoStart: false,
      wslDistro: process.env.OPENTALKING_WSL_DISTRO || "Ubuntu-22.04",
      createdAt: pkg.installedAt,
      updatedAt: pkg.updatedAt,
    };
    await this.refreshStatus("starting", null, this.currentProfile.apiPort);

    if (pkg.health === "unsupported" || pkg.health === "missing" || pkg.health === "error") {
      await this.refreshStatus("error", pkg.healthReason ?? "模型启动包暂不可用", this.currentProfile.apiPort);
      return this.status;
    }

    const apiPort = options.forcePort ?? (await choosePort(this.currentProfile.apiPort ?? DEFAULT_API_PORT));
    const packageRoot = this.packageStore.packageRootForRuntime(pkg);
    const isWsl = process.platform === "win32";
    const ffmpegBin = isWsl ? null : resolveExtraBinary("ffmpeg");
    const env = buildPackageEnv(pkg.manifest, packageRoot, apiPort, ffmpegBin);
    const command: DesktopCommand = isWsl
      ? this.packageStore.buildWslCommand(pkg, "start", this.currentPackageDistro(), env)
      : this.packageStore.buildNativeCommand(pkg, "start");
    const result = await runCommand(command.command, command.args, { cwd: command.cwd, env, timeoutMs: 180_000 });
    if (result.code !== 0) {
      await this.refreshStatus("error", result.stderr || result.stdout || `模型启动包启动失败：exit ${result.code}`, apiPort);
      return this.status;
    }
    this.startedByDesktop = true;
    const resolved = await this.resolvePackageApiBaseUrl(apiPort);
    await this.refreshStatus(resolved.ready ? "ready" : "error", resolved.ready ? null : resolved.error, apiPort, resolved.apiBaseUrl);
    return this.status;
  }

  async stopPackageBackend(packageId: string): Promise<DesktopStatus> {
    const pkg = await this.packageStore.get(packageId);
    if (pkg) {
      const isWsl = process.platform === "win32";
      const apiPort = this.status.apiPort ?? DEFAULT_API_PORT;
      const packageRoot = this.packageStore.packageRootForRuntime(pkg);
      const env = buildPackageEnv(pkg.manifest, packageRoot, apiPort, isWsl ? null : resolveExtraBinary("ffmpeg"));
      const command: DesktopCommand = isWsl
        ? this.packageStore.buildWslCommand(pkg, "stop", this.currentPackageDistro(), env)
        : this.packageStore.buildNativeCommand(pkg, "stop");
      await runCommand(command.command, command.args, { cwd: command.cwd, env, timeoutMs: 60_000 }).catch(() => null);
    }
    this.startedByDesktop = false;
    this.currentPackage = null;
    await this.refreshStatus("stopped");
    return this.status;
  }

  private startCommand(profile: BackendProfile, apiPort: number): { command: string; args: string[]; cwd?: string } {
    const modeArgs: string[] = profile.mode === "managed-mock" ? ["--mock"] : [];
    if (profile.mode === "managed-local" && profile.omnirtEndpoint) {
      modeArgs.push("--omnirt", profile.omnirtEndpoint);
    }
    modeArgs.push("--api-port", String(apiPort));

    if (process.platform === "win32") {
      const distro = profile.wslDistro || "Ubuntu-22.04";
      const repo = profile.wslRepoPath || "/home/opentalking/opentalking";
      const command = `cd ${bashQuote(repo)} && bash scripts/quickstart/start_opentalking.sh ${modeArgs
        .map(bashQuote)
        .join(" ")}`;
      return { command: "wsl.exe", args: ["-d", distro, "--", "bash", "-lc", command] };
    }

    const repoPath = profile.repoPath || findRepoRoot();
    return {
      command: "bash",
      args: ["scripts/quickstart/start_opentalking.sh", ...modeArgs],
      cwd: repoPath,
    };
  }

  private backendEnv(_profile: BackendProfile): NodeJS.ProcessEnv {
    const env = { ...process.env };
    const ffmpegBin = resolveExtraBinary("ffmpeg");
    if (ffmpegBin) {
      env.OPENTALKING_FFMPEG_BIN = ffmpegBin;
      env.PATH = `${path.dirname(ffmpegBin)}${path.delimiter}${env.PATH ?? ""}`;
    }
    return env;
  }

  private stopCommand(profile: BackendProfile, apiPort: number): { command: string; args: string[]; cwd?: string } {
    if (process.platform === "win32") {
      const distro = profile.wslDistro || "Ubuntu-22.04";
      const repo = profile.wslRepoPath || "/home/opentalking/opentalking";
      const command = `cd ${bashQuote(repo)} && bash scripts/quickstart/stop_all.sh --api-port ${bashQuote(String(apiPort))}`;
      return { command: "wsl.exe", args: ["-d", distro, "--", "bash", "-lc", command] };
    }
    const repoPath = profile.repoPath || findRepoRoot();
    return {
      command: "bash",
      args: ["scripts/quickstart/stop_all.sh", "--api-port", String(apiPort)],
      cwd: repoPath,
    };
  }

  private async refreshStatus(
    health: DesktopStatus["health"],
    error: string | null = null,
    apiPort?: number,
    resolvedApiBaseUrl?: string | null,
  ) {
    const profile = this.currentProfile;
    const apiBaseUrl =
      resolvedApiBaseUrl ??
      (profile?.mode === "remote"
        ? normalizeUrl(profile.apiBaseUrl ?? "")
        : apiPort || profile?.apiPort
          ? `http://127.0.0.1:${apiPort ?? profile?.apiPort}`
          : null);
    this.proxy.setTarget(apiBaseUrl);
    const modelsReachable = apiBaseUrl ? await checkModels(apiBaseUrl) : false;
    this.status = {
      ...this.blankStatus(health),
      profileId: profile?.id ?? null,
      profileName: profile?.name ?? null,
      packageId: this.currentPackage?.id ?? null,
      packageName: this.currentPackage?.title ?? null,
      mode: profile?.mode ?? null,
      apiBaseUrl,
      proxyBaseUrl: this.proxy.apiBaseUrl,
      apiPort: apiPort ?? profile?.apiPort ?? null,
      logPath: this.currentPackage?.logPath ?? (profile ? this.localLogPath(profile, apiPort ?? profile.apiPort ?? DEFAULT_API_PORT) : null),
      lastError: error,
      modelsReachable,
      health: error ? "error" : modelsReachable && health !== "stopped" ? "ready" : health,
      checkedAt: nowIso(),
    };
    BrowserWindow.getAllWindows().forEach((window) => {
      window.webContents.send(DESKTOP_CHANNELS.statusChanged, this.status);
    });
  }

  private blankStatus(health: DesktopStatus["health"]): DesktopStatus {
    return {
      platform: platform(),
      profileId: null,
      profileName: null,
      packageId: null,
      packageName: null,
      mode: null,
      health,
      apiBaseUrl: null,
      proxyBaseUrl: null,
      apiPort: null,
      pid: null,
      logPath: null,
      worksDir: this.paths.worksDir,
      homeDir: this.paths.homeDir,
      lastError: null,
      modelsReachable: false,
      checkedAt: nowIso(),
    };
  }

  private async resolveManagedApiBaseUrl(
    profile: BackendProfile,
    apiPort: number,
  ): Promise<{ apiBaseUrl: string; ready: boolean; error: string | null }> {
    const loopback = `http://127.0.0.1:${apiPort}`;
    if (await checkModels(loopback)) return { apiBaseUrl: loopback, ready: true, error: null };

    if (process.platform === "win32" && profile.wslRepoPath) {
      const result = await runCommand(
        "wsl.exe",
        ["-d", profile.wslDistro ?? "Ubuntu-22.04", "--", "bash", "-lc", "hostname -I"],
        { timeoutMs: 10_000 },
      ).catch(() => null);
      const ip = result ? firstIpv4(result.stdout) : null;
      if (ip) {
        const wslUrl = `http://${ip}:${apiPort}`;
        if (await checkModels(wslUrl)) return { apiBaseUrl: wslUrl, ready: true, error: null };
      }
      return {
        apiBaseUrl: loopback,
        ready: false,
        error: "后端已在 WSL2 中启动，但 Windows 侧无法访问 /models。请检查 WSL localhost 转发、防火墙，或确认 Ubuntu 网络地址可达。",
      };
    }

    return { apiBaseUrl: loopback, ready: false, error: "后端已启动，但 /models 暂不可达" };
  }

  private async resolvePackageApiBaseUrl(
    apiPort: number,
  ): Promise<{ apiBaseUrl: string; ready: boolean; error: string | null }> {
    const loopback = `http://127.0.0.1:${apiPort}`;
    if (await checkModels(loopback)) return { apiBaseUrl: loopback, ready: true, error: null };

    if (process.platform === "win32") {
      const result = await runCommand(
        "wsl.exe",
        ["-d", this.currentPackageDistro(), "--", "bash", "-lc", "hostname -I"],
        { timeoutMs: 10_000 },
      ).catch(() => null);
      const ip = result ? firstIpv4(result.stdout) : null;
      if (ip) {
        const wslUrl = `http://${ip}:${apiPort}`;
        if (await checkModels(wslUrl)) return { apiBaseUrl: wslUrl, ready: true, error: null };
      }
      return {
        apiBaseUrl: loopback,
        ready: false,
        error: "QuickTalk 启动包已在 WSL2 中启动，但 Windows 侧无法访问 /models。请检查 WSL localhost 转发、防火墙或 Ubuntu 网络地址。",
      };
    }

    return { apiBaseUrl: loopback, ready: false, error: "模型启动包已执行，但 /models 暂不可达" };
  }

  private currentPackageDistro(): string {
    return this.currentProfile?.wslDistro || process.env.OPENTALKING_WSL_DISTRO || "Ubuntu-22.04";
  }

  private localLogPath(profile: BackendProfile, apiPort: number): string {
    if (profile.mode === "managed-package" && this.currentPackage?.logPath) {
      return this.currentPackage.logPath;
    }
    if (process.platform === "win32" && profile.wslRepoPath) {
      return `wsl:${path.posix.join(path.posix.dirname(profile.wslRepoPath), "logs", `opentalking-api-${apiPort}.log`)}`;
    }
    const repoPath = profile.repoPath || findRepoRoot();
    return path.resolve(repoPath, "..", "logs", `opentalking-api-${apiPort}.log`);
  }

  logDir(): string {
    const profile = this.currentProfile;
    if (profile && process.platform !== "win32" && profile.mode !== "remote") {
      return path.dirname(this.localLogPath(profile, this.status.apiPort ?? profile.apiPort ?? DEFAULT_API_PORT));
    }
    return this.paths.logsDir;
  }
}

let mainWindow: BrowserWindow | null = null;
let backend: BackendController;
let packageStore: ModelPackageStore;

function createMainWindow(preloadPath: string) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    title: "OpenTalking Desktop",
    webPreferences: {
      preload: preloadPath,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    console.log(`[renderer:${level}] ${message} (${sourceId}:${line})`);
  });
  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedUrl) => {
    console.error(`[renderer:load-failed] ${errorCode} ${errorDescription} ${validatedUrl}`);
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    console.error(`[renderer:gone] ${details.reason}`);
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url).catch(() => null);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const devServerUrl = process.env.OPENTALKING_DESKTOP_DEV_SERVER_URL;
    if (devServerUrl && url.startsWith(devServerUrl)) return;
    if (url.startsWith("file://")) return;
    event.preventDefault();
  });

  const devServerUrl = process.env.OPENTALKING_DESKTOP_DEV_SERVER_URL;
  if (!app.isPackaged && devServerUrl) {
    mainWindow.loadURL(devServerUrl);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/main_window/index.html"));
  }
}

function registerIpc(store: ProfileStore, packages: ModelPackageStore) {
  ipcMain.handle(DESKTOP_CHANNELS.getStatus, () => backend.getStatus());
  ipcMain.handle(DESKTOP_CHANNELS.listProfiles, () => store.list());
  ipcMain.handle(DESKTOP_CHANNELS.saveProfile, (_event, profile: SaveProfileInput) => store.save(profile));
  ipcMain.handle(DESKTOP_CHANNELS.activateProfile, async (_event, id: string) => backend.activateProfile(id));
  ipcMain.handle(DESKTOP_CHANNELS.startBackend, async (_event, options?: StartBackendOptions) => backend.start(options));
  ipcMain.handle(DESKTOP_CHANNELS.stopBackend, () => backend.stop());
  ipcMain.handle(DESKTOP_CHANNELS.tailLogs, (_event, lines?: number) => backend.tailLogs(lines));
  ipcMain.handle(DESKTOP_CHANNELS.listPackages, () => packages.list());
  ipcMain.handle(DESKTOP_CHANNELS.importPackage, (_event, filePath?: string) => packages.importPackage(filePath));
  ipcMain.handle(DESKTOP_CHANNELS.deletePackage, (_event, id: string) => packages.deletePackage(id));
  ipcMain.handle(DESKTOP_CHANNELS.startPackageBackend, (_event, packageId: string, options?: StartBackendOptions) =>
    backend.startPackageBackend(packageId, options),
  );
  ipcMain.handle(DESKTOP_CHANNELS.stopPackageBackend, (_event, packageId: string) => backend.stopPackageBackend(packageId));
  ipcMain.handle(DESKTOP_CHANNELS.tailPackageLogs, (_event, packageId: string, lines?: number) => packages.tailLogs(packageId, lines));
  ipcMain.handle(DESKTOP_CHANNELS.openPath, async (_event, kind: OpenPathKind) => {
    const status = backend.getStatus();
    const targets: Record<OpenPathKind, string> = {
      works: status.worksDir,
      logs: backend.logDir(),
      home: status.homeDir,
    };
    ensureDir(targets[kind]);
    await shell.openPath(targets[kind]);
  });
}

function setupMenu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "OpenTalking",
        submenu: [
          { role: "about" },
          { type: "separator" },
          { label: "打开作品目录", click: () => backend && shell.openPath(backend.getStatus().worksDir) },
          { label: "打开日志目录", click: () => backend && shell.openPath(backend.logDir()) },
          { type: "separator" },
          { role: "quit" },
        ],
      },
      { label: "编辑", submenu: [{ role: "copy" }, { role: "paste" }, { role: "selectAll" }] },
      { label: "视图", submenu: [{ role: "reload" }, { role: "toggleDevTools" }, { role: "resetZoom" }] },
    ]),
  );
}

function resolvePreloadPath(): string {
  const candidates = [
    path.join(__dirname, "preload.cjs"),
    path.join(__dirname, "preload.js"),
    path.join(__dirname, "index.js"),
  ];
  const preloadPath = candidates.find((candidate) => existsSync(candidate));
  if (!preloadPath) throw new Error(`Preload bundle not found in ${__dirname}`);
  return preloadPath;
}

app.whenReady().then(async () => {
  const repoRoot = findRepoRoot();
  const userData = ensureDir(app.getPath("userData"));
  const homeDir = ensureDir(path.join(userData, "OpenTalking"));
  const worksDir = ensureDir(path.join(homeDir, "works"));
  const logsDir = ensureDir(path.join(homeDir, "logs"));
  const proxy = new DesktopProxy(path.resolve(repoRoot, "apps/web/dist"));
  await proxy.start();
  const store = new ProfileStore(userData, repoRoot);
  const runtimeOptions: PackageRuntimeOptions = {
    platform: platform(),
    arch: runtimeArch(),
    wslDistro: process.env.OPENTALKING_WSL_DISTRO || "Ubuntu-22.04",
  };
  packageStore = new ModelPackageStore({ userData, homeDir, logsDir }, runtimeOptions);
  backend = new BackendController(store, packageStore, proxy, { userData, homeDir, worksDir, logsDir });
  await backend.init();
  registerIpc(store, packageStore);
  setupMenu();
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(["media", "microphone", "camera"].includes(permission));
  });
  createMainWindow(resolvePreloadPath());
});

app.on("before-quit", (event) => {
  if (!backend) return;
  event.preventDefault();
  backend
    .stopIfStartedByDesktop()
    .catch(() => null)
    .finally(() => {
      app.exit(0);
    });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow(resolvePreloadPath());
  }
});
