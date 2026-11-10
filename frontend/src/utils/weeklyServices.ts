export interface ServiceSetup { file: string; issues: string[] }
export interface ServiceState { enabled: boolean; configured: boolean; setup?: ServiceSetup }
export const analysisLabels: Record<string, string> = {
  queued: "等待解析", running: "解析中", failed: "解析失败", completed: "已生成",
  available: "可解析", disabled: "未启用", unconfigured: "待配置",
};
export function serviceLabel(service: ServiceState) {
  if (!service.enabled) return "未启用";
  return service.configured ? "已启用" : "配置不完整";
}
