import { ChevronLeft, ChevronRight, HeartHandshake, QrCode, ReceiptText, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Language, SiteContent } from "../locales";

type DonationRecord = {
  name: string;
  message?: string;
  donatedAt: string;
  amountCny: number;
};

const pageSizes = [10, 20, 50] as const;
type PageSize = (typeof pageSizes)[number];

const parseDonationRecords = (value: unknown): DonationRecord[] => {
  if (!value || typeof value !== "object" || !Array.isArray((value as { records?: unknown }).records)) {
    return [];
  }

  return (value as { records: unknown[] }).records
    .flatMap((record) => {
      if (!record || typeof record !== "object") return [];

      const candidate = record as Partial<DonationRecord>;
      const name = typeof candidate.name === "string" ? candidate.name.trim() : "";
      const message = typeof candidate.message === "string" ? candidate.message.trim() : "";
      const donatedAt = typeof candidate.donatedAt === "string" ? candidate.donatedAt : "";
      const amountCny = Number(candidate.amountCny);

      if (!name || !donatedAt || !Number.isFinite(amountCny) || amountCny <= 0 || Number.isNaN(new Date(donatedAt).getTime())) {
        return [];
      }

      return [{ name, ...(message ? { message } : {}), donatedAt, amountCny }];
    })
    .sort((left, right) => new Date(right.donatedAt).getTime() - new Date(left.donatedAt).getTime());
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
  const [pageSize, setPageSize] = useState<PageSize>(10);
  const [currentPage, setCurrentPage] = useState(1);

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

  const pageCount = Math.max(1, Math.ceil(records.length / pageSize));
  const paginatedRecords = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return records.slice(start, start + pageSize);
  }, [currentPage, pageSize, records]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, pageCount));
  }, [pageCount]);

  const loadingLabel = language === "zh" ? "正在载入捐赠记录…" : "Loading donation records…";
  const pageStatus = language === "zh" ? `第 ${currentPage} / ${pageCount} 页` : `Page ${currentPage} of ${pageCount}`;

  return (
    <>
      <section className="relative overflow-hidden">
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
        <article className="panel-card relative overflow-hidden border-amber-100/65 p-6 shadow-[0_18px_42px_rgba(180,83,9,0.05)] md:p-7">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_88%_0%,rgba(245,158,11,0.07),transparent_34%),linear-gradient(135deg,rgba(255,251,235,0.4),rgba(254,243,199,0.14)_55%,rgba(255,247,237,0.26))]" />
          <div className="pointer-events-none absolute -right-12 -top-12 h-52 w-52 rounded-full bg-amber-300/9 blur-3xl" />
          <div className="relative">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">{copy.ledgerEyebrow}</p>
              <h2 className="mt-2 text-2xl font-semibold text-ink">{copy.ledgerTitle}</h2>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-indigo-950/70">{copy.ledgerDescription}</p>
            </div>

            <div className="mt-6 overflow-x-auto rounded-xl border border-indigo-100 bg-white/70" aria-busy={loading}>
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
              {!loading && records.length > 0 ? (
                <table className="w-full min-w-[860px] table-fixed border-collapse text-left">
                  <colgroup>
                    <col className="w-[22%]" />
                    <col className="w-[38%]" />
                    <col className="w-[24%]" />
                    <col className="w-[16%]" />
                  </colgroup>
                  <thead className="border-b border-indigo-100 bg-indigo-50/70 text-xs font-semibold text-indigo-950/65">
                    <tr>
                      <th scope="col" className="px-5 py-3 text-left">{copy.supporterLabel}</th>
                      <th scope="col" className="px-5 py-3 text-left">{copy.messageLabel}</th>
                      <th scope="col" className="px-5 py-3 text-left">{copy.donatedAtLabel}</th>
                      <th scope="col" className="px-5 py-3 text-right">{copy.amountLabel}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedRecords.map((record) => (
                      <tr key={`${record.name}-${record.donatedAt}-${record.amountCny}`} className="border-b border-indigo-50 last:border-b-0">
                        <td className="px-5 py-4 align-middle font-semibold text-ink">{record.name}</td>
                        <td className="px-5 py-4 align-middle text-sm leading-6 text-indigo-950/70">{record.message || copy.emptyMessageLabel}</td>
                        <td className="px-5 py-4 align-middle text-sm text-slate-500">
                          <time dateTime={record.donatedAt}>{formatDonationDate(record.donatedAt, language)}</time>
                        </td>
                        <td className="px-5 py-4 align-middle text-right text-sm font-semibold text-amber-700">{formatDonationAmount(record.amountCny, language)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
            </div>
            {!loading ? (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-sm font-medium text-slate-600">
                  <span>{copy.pageSizeLabel}</span>
                  <select
                    className="rounded-lg border border-indigo-100 bg-white px-2.5 py-1.5 text-sm font-semibold text-ink shadow-sm focus:outline-none focus:ring-2 focus:ring-cyanline"
                    value={pageSize}
                    onChange={(event) => {
                      setPageSize(Number(event.target.value) as PageSize);
                      setCurrentPage(1);
                    }}
                  >
                    {pageSizes.map((size) => <option key={size} value={size}>{size}</option>)}
                  </select>
                </label>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="focus-ring inline-flex h-9 items-center gap-1 rounded-lg border border-indigo-100 bg-white px-2.5 text-sm font-semibold text-ink shadow-sm transition hover:border-cyanline/40 hover:text-cyanline disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                    disabled={currentPage === 1}
                  >
                    <ChevronLeft className="h-4 w-4" aria-hidden />
                    {copy.previousPageLabel}
                  </button>
                  <span className="min-w-24 text-center text-sm font-medium text-slate-500">{pageStatus}</span>
                  <button
                    type="button"
                    className="focus-ring inline-flex h-9 items-center gap-1 rounded-lg border border-indigo-100 bg-white px-2.5 text-sm font-semibold text-ink shadow-sm transition hover:border-cyanline/40 hover:text-cyanline disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => setCurrentPage((page) => Math.min(pageCount, page + 1))}
                    disabled={currentPage === pageCount}
                  >
                    {copy.nextPageLabel}
                    <ChevronRight className="h-4 w-4" aria-hidden />
                  </button>
                </div>
              </div>
            ) : null}
            <p className="mt-4 text-xs leading-6 text-slate-500">{copy.privacyNotice}</p>
          </div>
        </article>

        <article className="panel-card mt-6 grid gap-5 p-4 md:p-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(250px,0.8fr)] lg:items-stretch">
          <section className="flex min-h-full flex-col justify-center rounded-2xl border border-indigo-100 bg-white/65 p-4 md:p-5">
            <p className="eyebrow">{copy.usageEyebrow}</p>
            <h2 className="mt-3 text-3xl font-semibold leading-tight text-ink">{copy.usageTitle}</h2>
            <ul className="mt-5 grid gap-2.5 sm:grid-cols-2">
              {copy.usageItems.map((item) => (
                <li key={item} className="flex gap-3 rounded-xl border border-indigo-100 bg-white/80 p-3 text-sm leading-6 text-indigo-950/70 shadow-sm">
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-cyanline" aria-hidden />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="flex flex-col justify-center border-t border-indigo-100 pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl border border-amber-200 bg-amber-50 text-amber-700">
                <QrCode className="h-5 w-5" aria-hidden />
              </span>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">{copy.qrEyebrow}</p>
                <h2 className="mt-1 text-xl font-semibold text-ink">{copy.qrTitle}</h2>
              </div>
            </div>
            <p className="mt-3 text-sm leading-6 text-indigo-950/70">{copy.qrDescription}</p>
            <div className="mt-4 rounded-2xl border border-amber-100 bg-amber-50/60 p-3">
              <img
                src="/images/donation_qrcode.jpg"
                alt={language === "zh" ? "OpenTalking 捐赠二维码" : "OpenTalking donation QR code"}
                className="mx-auto aspect-square w-full max-w-[220px] rounded-xl bg-white object-contain"
              />
            </div>
            <p className="mt-3 text-center text-xs font-semibold text-slate-500">{copy.qrCaption}</p>
          </section>
        </article>
      </section>
    </>
  );
}
