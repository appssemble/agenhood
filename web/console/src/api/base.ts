// Single source of truth for the API origin. Empty string means same-origin
// (requests go to relative paths); set VITE_API_BASE to an explicit http origin
// in dev/split-deploy setups.
export const API_BASE = import.meta.env.VITE_API_BASE ?? "";
