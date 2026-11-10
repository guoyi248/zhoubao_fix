export interface Period { id: string; iso_year: number; iso_week: number; start_date: string; end_date: string; deadline: string }
export interface ReportRow {
  id: string; reporting_period_id: string; owner_name: string; period_label: string;
  status: string; updated_at: string; current_revision_id: string | null;
  submitted_at: string | null; revision_no: number | null; published_filename: string;
}
export interface TeamReport extends ReportRow { analysis_status: string; progress_summary: string }
export interface Overview { period: Period; periods: Period[]; is_current: boolean; submitted: TeamReport[]; missing: { id: number; name: string }[] }
export function weekRange(p: Period) {
  const short = (s: string) => s.slice(5).split("-").map(Number).join(".");
  return short(p.start_date) + " – " + short(p.end_date);
}
export function dateText(value: string, time = false) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", ...(time ? { hour:"2-digit", minute:"2-digit", hourCycle:"h23" as const } : {}) }).format(new Date(value));
}
export const reportStatus: Record<string, string> = { draft: "草稿", submitted: "已提交", resubmitted: "更正中", archived: "已归档" };
