export type BackendMode = "managed-mock" | "managed-local" | "managed-package" | "remote";

export type DesktopPlatform = "darwin" | "win32" | "linux";

export type BackendHealth = "stopped" | "starting" | "ready" | "error";

export type PackageHealth = "missing" | "compatible" | "unsupported" | "ready" | "error";

export type ModelPackagePlatform = {
  os: DesktopPlatform;
  arch?: string | string[];
  runtime?: "native" | "wsl2";
  supported?: boolean;
  message?: string;
};

export type ModelPackageManifest = {
  schemaVersion: 1;
  id: string;
  title: string;
  version: string;
  model: string;
  backend: "local" | "omnirt" | "direct_ws" | "mock";
  platforms: ModelPackagePlatform[];
  entry: {
    start: string;
    stop: string;
    diagnose?: string;
    cwd?: string;
  };
  health: {
    expectModel: string;
  };
  env: Record<string, string>;
  resources: {
    requiredFiles: string[];
  };
};

export type InstalledModelPackage = {
  id: string;
  title: string;
  version: string;
  model: string;
  backend: ModelPackageManifest["backend"];
  manifest: ModelPackageManifest;
  installPath?: string;
  wslInstallPath?: string;
  logPath?: string;
  health: PackageHealth;
  healthReason: string | null;
  installedAt: string;
  updatedAt: string;
};

export type BackendProfile = {
  id: string;
  name: string;
  mode: BackendMode;
  apiPort?: number;
  repoPath?: string;
  omnirtEndpoint?: string;
  autoStart?: boolean;
  wslDistro?: string;
  wslRepoPath?: string;
  apiBaseUrl?: string;
  lastCheckedAt?: string;
  createdAt: string;
  updatedAt: string;
};

export type DesktopStatus = {
  platform: DesktopPlatform;
  profileId: string | null;
  profileName: string | null;
  packageId: string | null;
  packageName: string | null;
  mode: BackendMode | null;
  health: BackendHealth;
  apiBaseUrl: string | null;
  proxyBaseUrl: string | null;
  apiPort: number | null;
  pid: number | null;
  logPath: string | null;
  worksDir: string;
  homeDir: string;
  lastError: string | null;
  modelsReachable: boolean;
  checkedAt: string;
};

export type SaveProfileInput = Omit<BackendProfile, "id" | "createdAt" | "updatedAt"> & {
  id?: string;
};

export type StartBackendOptions = {
  profileId?: string;
  forcePort?: number;
};

export type OpenPathKind = "works" | "logs" | "home";

export type DesktopApi = {
  getStatus(): Promise<DesktopStatus>;
  listProfiles(): Promise<BackendProfile[]>;
  saveProfile(profile: SaveProfileInput): Promise<BackendProfile>;
  activateProfile(id: string): Promise<DesktopStatus>;
  startBackend(options?: StartBackendOptions): Promise<DesktopStatus>;
  stopBackend(): Promise<DesktopStatus>;
  tailLogs(lines?: number): Promise<string>;
  openPath(kind: OpenPathKind): Promise<void>;
  listPackages(): Promise<InstalledModelPackage[]>;
  importPackage(filePath?: string): Promise<InstalledModelPackage>;
  deletePackage(id: string): Promise<void>;
  startPackageBackend(packageId: string, options?: StartBackendOptions): Promise<DesktopStatus>;
  stopPackageBackend(packageId: string): Promise<DesktopStatus>;
  tailPackageLogs(packageId: string, lines?: number): Promise<string>;
  onStatusChanged(callback: (status: DesktopStatus) => void): () => void;
};

export const DESKTOP_CHANNELS = {
  getStatus: "desktop:get-status",
  listProfiles: "desktop:list-profiles",
  saveProfile: "desktop:save-profile",
  activateProfile: "desktop:activate-profile",
  startBackend: "desktop:start-backend",
  stopBackend: "desktop:stop-backend",
  tailLogs: "desktop:tail-logs",
  openPath: "desktop:open-path",
  listPackages: "desktop:list-packages",
  importPackage: "desktop:import-package",
  deletePackage: "desktop:delete-package",
  startPackageBackend: "desktop:start-package-backend",
  stopPackageBackend: "desktop:stop-package-backend",
  tailPackageLogs: "desktop:tail-package-logs",
  statusChanged: "desktop:status-changed",
} as const;
