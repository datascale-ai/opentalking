type AnalyticsPayload = {
  eventName: "page_view" | "video_play";
  path: string;
  language: "zh" | "en";
  page?: string;
  caseSlug?: string;
  videoId?: string;
};

const analyticsEndpoint = "/analytics/event";
const sourceReferrers: Record<string, string> = {
  "#github": "https://github.com/datascale-ai/opentalking",
};
const sourceReferrer = sourceReferrers[window.location.hash.toLowerCase()];
const initialReferrer = sourceReferrer ?? document.referrer;

if (sourceReferrer) {
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
}

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
