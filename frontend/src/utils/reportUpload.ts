import api from "@/utils/api";

export interface ReportAttachment {
  id: string;
  original_filename: string;
  uploaded_filename: string;
  status: string;
  file_size_bytes: number;
  preview_status: { available: boolean } | null;
}

export const reportFileAccept = ".docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.md";

export async function sendReportFile(url: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<ReportAttachment>(url, form, { headers: { "Content-Type": "multipart/form-data" } });
  return data;
}
