import { HeartHandshake, QrCode, ReceiptText, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Language, SiteContent } from "../locales";

type DonationRecord = {
  name: string;
  donatedAt: string;
  amountCny: number;
};

const parseDonationRecords = (value: unknown): DonationRecord[] => {
  if (!value || typeof value !== "object" || !Array.isArray((value as { records?: unknown }).records)) {
    return [];
  }

  return (value as { records: unknown[] }).records.flatMap((record) => {
    if (!record || typeof record !== "object") return [];

    const candidate = record as Partial<DonationRecord>;
    const name = typeof candidate.name === "string" ? candidate.name.trim() : "";
    const donatedAt = typeof candidate.donatedAt === "string" ? candidate.donatedAt : "";
    const amountCny = Number(candidate.amountCny);

    if (!name || !donatedAt || !Number.isFinite(amountCny) || amountCny <= 0 || Number.isNaN(new Date(donatedAt).getTime())) {
      return [];
    }

    return [{ name, donatedAt, amountCny }];
  }).sort((left, right) => new Date(right.donatedAt).getTime() - new Date(left.donatedAt).getTime());
};

const formatDonationDate = (value: string, language: Language) =>
  new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));

const formatDonationAmount = (amount: number, language: Language) =>
  new Intl.NumberFormat(language === "zh" ? "zh-CN" : "en-US", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

type DonationPageProps = {
  language: Language;
  copy: SiteContent["donation"];
};

export function DonationPage({ language, copy }: DonationPageProps) {
  const [records, setRecords] = useState<DonationRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    const loadDonationRecords = async () => {
      try {
        const response = await fetch("/donations.json", { cache: "no-store" });
        const payload = response.ok ? await response.json() : null;
        if (active) setRecords(parseDonationRecords(payload));
      } catch {
        if (active) setRecords([]);
      } finally {
        if (active) setLoading(false);
      }
    };

    void loadDonationRecords();
    return () => {
      active = false;
    };
  }, []);

  const totalAmount = useMemo(
    () => records.reduce((sum, record) => sum + record.amountCny, 0),
    [records],
  );

  const loadingLabel = language === "zh" ? "正在载入捐赠记录…" : "Loading donation records…";

  return (
    <>
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(125deg,rgba(245,158,11,0.16),rgba(255,255,255,0)_42%),linear-gradient(248deg,rgba(251,113,133,0.15),rgba(255,255,255,0)_36%)]" />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(245,158,11,0.48),rgba(251,113,133,0.4),transparent)]" />
        <div className="page-hero relative">
          <p className="eyebrow">{copy.eyebrow}</p>
          <div className="mt-5 flex flex-wrap items-center gap-4">
            <span className="grid h-14 w-14 place-items-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-700 shadow-sm">
              <HeartHandshake className="h-7 w-7" aria-hidden />
            </span>
            <h1 className="text-4xl font-semibold leading-tight tracking-normal text-ink md:text-6xl">{copy.title}</h1>
          </div>
          <p className="page-copy">{copy.intro}</p>
        </div>
      </section>

      <section className="section-container pt-2 md:pt-4">
        <div className="grid gap-6 lg:grid-cols-[0.78fr_1.22fr]">
          <article className="panel-card relative overflow-hidden p-6 md:p-7">
            <div className="pointer-events-none absolute -right-10 -top-10 h-36 w-36 rounded-full bg-amber-100/70 blur-2xl" />
            <div className="relative">
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-xl border border-amber-200 bg-amber-50 text-amber-700">
                  <QrCode className="h-5 w-5" aria-hidden />
                </span>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">{copy.qrEyebrow}</p>
                  <h2 className="mt-1 text-xl font-semibold text-ink">{copy.qrTitle}</h2>
                </div>
              </div>
              <p className="mt-5 text-sm leading-7 text-indigo-950/70">{copy.qrDescription}</p>
              <div className="mt-5 rounded-2xl border border-amber-100 bg-amber-50/60 p-3">
                <img
                  src="/images/donation_qrcode.jpg"
                  alt={language === "zh" ? "OpenTalking 捐赠二维码" : "OpenTalking donation QR code"}
                  className="mx-auto aspect-square w-full max-w-[270px] rounded-xl bg-white object-contain"
                />
              </div>
              <p className="mt-4 text-center text-xs font-semibold text-slate-500">{copy.qrCaption}</p>
            </div>
          </article>

          <article className="panel-card p-6 md:p-7">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyanline">{copy.ledgerEyebrow}</p>
                <h2 className="mt-2 text-2xl font-semibold text-ink">{copy.ledgerTitle}</h2>
                <p className="mt-3 max-w-xl text-sm leading-7 text-indigo-950/70">{copy.ledgerDescription}</p>
              </div>
              {records.length > 0 ? (
                <span className="w-fit rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-800">
                  {formatDonationAmount(totalAmount, language)}
                </span>
              ) : null}
            </div>

            <div className="mt-6 overflow-hidden rounded-xl border border-indigo-100 bg-white/70" aria-busy={loading}>
              <div className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_auto] gap-4 border-b border-indigo-100 bg-indigo-50/70 px-5 py-3 text-xs font-semibold text-indigo-950/65 sm:grid">
                <span>{copy.supporterLabel}</span>
                <span>{copy.donatedAtLabel}</span>
                <span className="text-right">{copy.amountLabel}</span>
              </div>
              {loading ? (
                <div className="flex min-h-48 items-center justify-center gap-3 px-5 py-10 text-sm font-medium text-slate-500">
                  <Sparkles className="h-5 w-5 animate-pulse text-amber-600" aria-hidden />
                  {loadingLabel}
                </div>
              ) : null}
              {!loading && records.length === 0 ? (
                <div className="flex min-h-48 flex-col items-center justify-center px-5 py-10 text-center">
                  <span className="grid h-11 w-11 place-items-center rounded-xl border border-indigo-100 bg-indigo-50 text-cyanline">
                    <ReceiptText className="h-5 w-5" aria-hidden />
                  </span>
                  <h3 className="mt-4 text-base font-semibold text-ink">{copy.emptyTitle}</h3>
                  <p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">{copy.emptyDescription}</p>
                </div>
              ) : null}
              {!loading && records.map((record) => (
                <div key={`${record.name}-${record.donatedAt}-${record.amountCny}`} className="grid gap-1 border-b border-indigo-50 px-5 py-4 last:border-b-0 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_auto] sm:items-center sm:gap-4">
                  <span className="font-semibold text-ink">{record.name}</span>
                  <time className="text-sm text-slate-500" dateTime={record.donatedAt}>{formatDonationDate(record.donatedAt, language)}</time>
                  <span className="text-sm font-semibold text-amber-700 sm:text-right">{formatDonationAmount(record.amountCny, language)}</span>
                </div>
              ))}
            </div>
          </article>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <section className="rounded-2xl border border-amber-100 bg-gradient-to-br from-amber-50/90 via-white to-rose-50/70 p-6 shadow-sm md:p-8">
            <p className="eyebrow text-amber-700">{copy.usageEyebrow}</p>
            <h2 className="mt-3 text-2xl font-semibold text-ink md:text-3xl">{copy.usageTitle}</h2>
            <ul className="mt-6 grid gap-3">
              {copy.usageItems.map((item) => (
                <li key={item} className="flex gap-3 text-sm leading-6 text-indigo-950/70">
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="cta-panel flex flex-col justify-center p-6 md:p-8">
            <HeartHandshake className="h-7 w-7 text-amber-200" aria-hidden />
            <h2 className="mt-5 text-2xl font-semibold text-white">{copy.thanksTitle}</h2>
            <p className="mt-3 text-sm leading-7 text-indigo-100">{copy.thanksDescription}</p>
            <p className="mt-6 border-t border-white/15 pt-4 text-xs leading-6 text-indigo-200">{copy.privacyNotice}</p>
          </section>
        </div>
      </section>
    </>
  );
}
