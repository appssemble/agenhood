import React from "react";
import { Icons, type IconName } from "./Icon";

type EmptyStateProps = {
  /** Icon name from the shared set, or a custom node. Rendered inside a rounded tile. */
  icon?: IconName | React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Optional CTA(s) — typically a button or link. */
  actions?: React.ReactNode;
  /** "md" (default) for page/card lists, "sm" for compact panels and sidebars. */
  size?: "sm" | "md";
  className?: string;
  style?: React.CSSProperties;
};

/**
 * Unified empty-state for lists, tables and collections: a centered icon tile,
 * a bold title, a muted one-line hint and optional actions. Use `EmptyRow` to
 * drop one into a table body.
 */
export function EmptyState({ icon, title, description, actions, size = "md", className = "", style }: EmptyStateProps) {
  const iconNode =
    typeof icon === "string"
      ? React.createElement(Icons[icon as IconName], { w: size === "sm" ? 20 : 24 })
      : icon;
  return (
    <div className={`empty empty-${size} ${className}`.trim()} style={style}>
      {iconNode && (
        <span className="empty-ico" aria-hidden>
          {iconNode}
        </span>
      )}
      <span className="empty-title">{title}</span>
      {description && <span className="empty-desc">{description}</span>}
      {actions && <div className="empty-actions">{actions}</div>}
    </div>
  );
}

/** Table-friendly wrapper: renders an `EmptyState` inside a full-width `<tr><td>`. */
export function EmptyRow({ colSpan, ...props }: EmptyStateProps & { colSpan: number }) {
  return (
    <tr>
      <td colSpan={colSpan} className="empty-cell">
        <EmptyState {...props} />
      </td>
    </tr>
  );
}
