import { API_BASE } from "./base";

export function containerFileRawPath(containerId: string, path: string): string {
  return `/v1/containers/${containerId}/files/raw?path=${encodeURIComponent(path)}`;
}

export function containerFileRawUrl(containerId: string, path: string): string {
  return `${API_BASE}${containerFileRawPath(containerId, path)}`;
}
