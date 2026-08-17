import type { DesktopApi } from "../shared/types";

declare global {
  interface Window {
    openTalkingDesktop: DesktopApi;
  }
}

export {};
