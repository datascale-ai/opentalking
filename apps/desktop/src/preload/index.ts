import { contextBridge, ipcRenderer } from "electron";
import {
  DESKTOP_CHANNELS,
  type BackendProfile,
  type DesktopApi,
  type DesktopStatus,
  type InstalledModelPackage,
  type OpenPathKind,
  type SaveProfileInput,
  type StartBackendOptions,
} from "../shared/types";

const desktopApi: DesktopApi = {
  getStatus() {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.getStatus) as Promise<DesktopStatus>;
  },
  listProfiles() {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.listProfiles) as Promise<BackendProfile[]>;
  },
  saveProfile(profile: SaveProfileInput) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.saveProfile, profile) as Promise<BackendProfile>;
  },
  activateProfile(id: string) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.activateProfile, id) as Promise<DesktopStatus>;
  },
  startBackend(options?: StartBackendOptions) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.startBackend, options) as Promise<DesktopStatus>;
  },
  stopBackend() {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.stopBackend) as Promise<DesktopStatus>;
  },
  tailLogs(lines?: number) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.tailLogs, lines) as Promise<string>;
  },
  openPath(kind: OpenPathKind) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.openPath, kind) as Promise<void>;
  },
  listPackages() {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.listPackages) as Promise<InstalledModelPackage[]>;
  },
  importPackage(filePath?: string) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.importPackage, filePath) as Promise<InstalledModelPackage>;
  },
  deletePackage(id: string) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.deletePackage, id) as Promise<void>;
  },
  startPackageBackend(packageId: string, options?: StartBackendOptions) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.startPackageBackend, packageId, options) as Promise<DesktopStatus>;
  },
  stopPackageBackend(packageId: string) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.stopPackageBackend, packageId) as Promise<DesktopStatus>;
  },
  tailPackageLogs(packageId: string, lines?: number) {
    return ipcRenderer.invoke(DESKTOP_CHANNELS.tailPackageLogs, packageId, lines) as Promise<string>;
  },
  onStatusChanged(callback: (status: DesktopStatus) => void) {
    const listener = (_event: Electron.IpcRendererEvent, status: DesktopStatus) => callback(status);
    ipcRenderer.on(DESKTOP_CHANNELS.statusChanged, listener);
    return () => ipcRenderer.removeListener(DESKTOP_CHANNELS.statusChanged, listener);
  },
};

contextBridge.exposeInMainWorld("openTalkingDesktop", desktopApi);
