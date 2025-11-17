/* ──────────────────────────────────────────────
   Icon set — 24-px grid, 2-px stroke, round caps
   Ported verbatim from design/icons.jsx
   ────────────────────────────────────────────── */
import React from "react";

type IcoProps = { w?: number; sw?: number; className?: string; title?: string; t?: string; style?: React.CSSProperties };

function Ico({ w = 14, sw = 2, className = "icon", t, style, children }: IcoProps & { children: React.ReactNode }) {
  return (
    <svg className={className} viewBox="0 0 24 24" width={w} height={w} strokeWidth={sw} style={style}
      fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      {t ? <g transform={t}>{children}</g> : children}
    </svg>
  );
}

export const Dashboard = (p: IcoProps) => <Ico {...p}><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></Ico>;
export const Container = (p: IcoProps) => <Ico {...p}><rect x="4" y="6" width="16" height="12" rx="2"/><path d="M8 12h.01"/></Ico>;
export const Tasks = (p: IcoProps) => <Ico {...p}><path d="M5 3h9l5 5v13a2 2 0 0 1-2 2H5z"/><path d="M14 3v5h5"/></Ico>;
export const Templates = (p: IcoProps) => <Ico {...p}><rect x="3" y="3" width="18" height="7" rx="1"/><rect x="3" y="14" width="9" height="7" rx="1"/><rect x="15" y="14" width="6" height="7" rx="1"/></Ico>;
// Prompt — a terminal (command glyph: chevron + cursor) with a big AI-sparkle sitting in a missing top-right corner.
// Box mirrors Lucide `square-terminal` but is an open path: the border stops on the top edge and resumes on the right
// edge, leaving the corner empty for the spark (Lucide `sparkle`, scaled — long arms + rounded shoulders read as a true sparkle).
export const Prompt = (p: IcoProps) => <Ico {...p}><path d="M19 14V18.5a2.5 2.5 0 0 1-2.5 2.5H4a2.5 2.5 0 0 1-2.5-2.5V8.5a2.5 2.5 0 0 1 2.5-2.5H10"/><path d="m5.5 10.5 3 3-3 3"/><path d="M11 16.5h4"/><g transform="translate(10.3 -1) scale(0.6)"><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z" fill="currentColor" stroke="none"/></g></Ico>;
export const Workflow = (p: IcoProps) => <Ico {...p}><rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="3" y="15" width="6" height="6" rx="1.5"/><rect x="15" y="9" width="6" height="6" rx="1.5"/><path d="M9 6h4a2 2 0 0 1 2 2v4"/><path d="M9 18h4a2 2 0 0 0 2-2v-4"/></Ico>;
export const Calendar = (p: IcoProps) => <Ico {...p}><rect x="3" y="4.5" width="18" height="16.5" rx="2"/><path d="M8 2.5v4"/><path d="M16 2.5v4"/><path d="M3 9.5h18"/></Ico>;
export const Users = (p: IcoProps) => <Ico {...p}><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></Ico>;
export const Key = (p: IcoProps) => <Ico {...p}><circle cx="9" cy="14" r="4"/><path d="m13 11 5-5 3 3-3 3-3-3"/></Ico>;
export const Credentials = (p: IcoProps) => <Ico {...p}><rect x="3" y="8" width="18" height="13" rx="2"/><path d="M7 8V5a5 5 0 0 1 10 0v3"/></Ico>;
export const Settings = (p: IcoProps) => <Ico {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></Ico>;
export const Profile = (p: IcoProps) => <Ico {...p}><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></Ico>;
export const File = (p: IcoProps) => <Ico {...p}><path d="M5 3h9l5 5v13a2 2 0 0 1-2 2H5z"/><path d="M14 3v5h5"/></Ico>;
export const Folder = (p: IcoProps) => <Ico {...p}><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></Ico>;
export const Search = (p: IcoProps) => <Ico {...p}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></Ico>;
export const Play = (p: IcoProps) => <Ico {...p}><polygon points="6 4 20 12 6 20 6 4"/></Ico>;
export const Pause = (p: IcoProps) => <Ico {...p}><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></Ico>;
export const Stop = (p: IcoProps) => <Ico {...p}><rect x="6" y="6" width="12" height="12" rx="2"/></Ico>;
export const Plus = (p: IcoProps) => <Ico {...p}><path d="M12 4v16M4 12h16"/></Ico>;
export const Check = (p: IcoProps) => <Ico {...p}><path d="m4 12 5 5L20 6"/></Ico>;
export const Close = (p: IcoProps) => <Ico {...p}><path d="m6 6 12 12M6 18 18 6"/></Ico>;
export const Arrow = (p: IcoProps) => <Ico {...p}><path d="M5 12h14"/><polyline points="12 5 19 12 12 19"/></Ico>;
export const ArrowLeft = (p: IcoProps) => <Ico {...p}><path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/></Ico>;
export const ArrowDown = (p: IcoProps) => <Ico {...p}><polyline points="6 9 12 15 18 9"/></Ico>;
export const ArrowUp = (p: IcoProps) => <Ico {...p}><polyline points="6 15 12 9 18 15"/></Ico>;
export const ArrowRight = (p: IcoProps) => <Ico {...p}><polyline points="9 6 15 12 9 18"/></Ico>;
export const Refresh = (p: IcoProps) => <Ico {...p}><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></Ico>;
// History — clock with a counter-clockwise rewind arrow (past tasks / activity).
export const History = (p: IcoProps) => <Ico {...p}><path d="M3 12a9 9 0 1 0 9-9 9.7 9.7 0 0 0-6.7 2.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></Ico>;
export const Clock = (p: IcoProps) => <Ico {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></Ico>;
export const Filter = (p: IcoProps) => <Ico {...p}><path d="M3 5h18M6 12h12M10 19h4"/></Ico>;
export const Info = (p: IcoProps) => <Ico {...p}><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></Ico>;
export const Warn = (p: IcoProps) => <Ico {...p}><path d="M12 2 2 22h20z"/><path d="M12 10v5M12 18h.01"/></Ico>;
export const Bell = (p: IcoProps) => <Ico {...p}><path d="M6 8a6 6 0 0 1 12 0v5l2 3H4l2-3z"/><path d="M10 19a2 2 0 0 0 4 0"/></Ico>;
export const Send = (p: IcoProps) => <Ico {...p}><path d="M3 12 21 4l-7 18-3-8z"/></Ico>;
export const Bolt = (p: IcoProps) => <Ico {...p}><path d="M13 2 3 14h7l-1 8 10-12h-7z"/></Ico>;
export const Web = (p: IcoProps) => <Ico {...p}><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></Ico>;
export const Terminal = (p: IcoProps) => <Ico {...p}><rect x="3" y="4" width="18" height="16" rx="2"/><polyline points="7 9 10 12 7 15"/><path d="M13 16h5"/></Ico>;
export const Pin = (p: IcoProps) => <Ico {...p}><path d="m12 2 4 6 6 1-4 4 1 6-7-3-7 3 1-6-4-4 6-1z" fill="none"/></Ico>;
export const Copy = (p: IcoProps) => <Ico {...p}><rect x="8" y="8" width="13" height="13" rx="2"/><path d="M3 16V5a2 2 0 0 1 2-2h11"/></Ico>;
export const Eye = (p: IcoProps) => <Ico {...p}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></Ico>;
export const Trash = (p: IcoProps) => <Ico {...p}><path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><path d="M6 7v13a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7"/></Ico>;
export const Pencil = (p: IcoProps) => <Ico {...p}><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></Ico>;
export const Download = (p: IcoProps) => <Ico {...p}><path d="M12 4v12"/><polyline points="6 10 12 16 18 10"/><path d="M4 20h16"/></Ico>;
export const Upload = (p: IcoProps) => <Ico {...p}><path d="M12 20V8"/><polyline points="6 14 12 8 18 14"/><path d="M4 4h16"/></Ico>;
export const Sliders = (p: IcoProps) => <Ico {...p}><path d="M4 6h11M4 12h7M4 18h13"/><circle cx="18" cy="6" r="2"/><circle cx="14" cy="12" r="2"/><circle cx="20" cy="18" r="2"/></Ico>;
export const Question = (p: IcoProps) => <Ico {...p}><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5"/><path d="M12 17h.01"/></Ico>;
export const Sparkles = (p: IcoProps) => <Ico {...p}><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/></Ico>;
export const Star = (p: IcoProps) => <Ico {...p}><polygon points="12 3 14.5 9 21 9.5 16 14 17.5 20.5 12 17 6.5 20.5 8 14 3 9.5 9.5 9"/></Ico>;
export const Server = (p: IcoProps) => <Ico {...p}><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01"/><path d="M7 16.5h.01"/></Ico>;
export const Checklist = (p: IcoProps) => <Ico {...p}><path d="M10 6h9"/><path d="M10 12h9"/><path d="M10 18h9"/><path d="m3 5.5 1.4 1.4L7.2 4"/><path d="m3 11.5 1.4 1.4L7.2 10"/><path d="m3 17.5 1.4 1.4L7.2 16"/></Ico>;
export const Logout = (p: IcoProps) => <Ico {...p}><path d="M10 18H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/><polyline points="15 15 18 12 15 9"/><path d="M18 12H10"/></Ico>;
export const Puzzle = (p: IcoProps) => <Ico {...p}><path d="M4 7h3a1 1 0 0 0 1-1V5a2 2 0 0 1 4 0v1a1 1 0 0 0 1 1h3a1 1 0 0 1 1 1v3a1 1 0 0 0 1 1h1a2 2 0 0 1 0 4h-1a1 1 0 0 0-1 1v3a1 1 0 0 1-1 1h-3a1 1 0 0 1-1-1v-1a2 2 0 0 0-4 0v1a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a2 2 0 0 0 0-4H5a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1Z"/></Ico>;

// Driver marks — stroke style, matching the rest of the icon set.
export const Cube = (p: IcoProps) => <Ico {...p}><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></Ico>;
export const Code = (p: IcoProps) => <Ico {...p}><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></Ico>;
export const Bot = (p: IcoProps) => <Ico {...p}><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></Ico>;

// Logs — log/activity lines with leading markers (API activity panel).
export const Logs = (p: IcoProps) => <Ico {...p}><path d="M8 6h12M8 12h12M8 18h8"/><path d="M4 6h.01M4 12h.01M4 18h.01"/></Ico>;
// Menu — hamburger for the mobile nav drawer.
export const Menu = (p: IcoProps) => <Ico {...p}><path d="M3 6h18M3 12h18M3 18h18"/></Ico>;
// Cpu/chip — represents the language model (the inference core + its I/O pins).
export const Cpu = (p: IcoProps) => <Ico {...p}><rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/></Ico>;
// Coins — stacked coins; used for token usage / spend metrics.
export const Coins = (p: IcoProps) => <Ico {...p}><circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/></Ico>;
// Wrench — represents the agent's callable tools.
export const Wrench = (p: IcoProps) => <Ico {...p}><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></Ico>;

export const Icons = {
  Dashboard,
  Container,
  Tasks,
  Templates,
  Prompt,
  Workflow,
  Calendar,
  Users,
  Key,
  Credentials,
  Settings,
  Profile,
  File,
  Folder,
  Search,
  Play,
  Pause,
  Stop,
  Plus,
  Check,
  Close,
  Arrow,
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  ArrowRight,
  Refresh,
  History,
  Clock,
  Filter,
  Info,
  Warn,
  Bell,
  Send,
  Bolt,
  Web,
  Terminal,
  Pin,
  Copy,
  Eye,
  Trash,
  Pencil,
  Download,
  Upload,
  Sliders,
  Question,
  Sparkles,
  Star,
  Server,
  Checklist,
  Logout,
  Puzzle,
  Cube,
  Code,
  Bot,
  Cpu,
  Coins,
  Wrench,
  Logs,
  Menu,
} as const;

export type IconName = keyof typeof Icons;
