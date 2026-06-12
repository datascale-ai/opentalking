type AnalyticsPayload = {
  eventName: "page_view" | "video_play";
  path: string;
  language: "zh" | "en";
  page?: string;
  caseSlug?: string;
  videoId?: string;
};

const analyticsEndpoint = "/analytics/event";
const initialReferrer = document.referrer;

export const trackAnalyticsEvent = (payload: AnalyticsPayload) => {
  const body = JSON.stringify({
    ...payload,
    referrer: initialReferrer,
    screen: `${window.screen.width}x${window.screen.height}`,
  });

  if (navigator.sendBeacon) {
    const blob = new Blob([body], { type: "application/json" });
    navigator.sendBeacon(analyticsEndpoint, blob);
    return;
  }

  void fetch(analyticsEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {
    // Analytics must never affect the public website experience.
  });
};
