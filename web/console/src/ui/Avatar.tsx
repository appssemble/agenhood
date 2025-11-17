export function Avatar({ name, size = 30 }: { name?: string | null; size?: number }) {
  const initials = (name ?? "").split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase();
  return (
    <span style={{ width: size, height: size, fontSize: size * 0.4 }}
      className="avatar">
      {initials}
    </span>
  );
}
