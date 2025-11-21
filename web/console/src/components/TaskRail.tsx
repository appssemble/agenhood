/** Activity-tab context rail: iteration steps and tools used. */
export function TaskRail({
  steps,
  tools,
}: {
  steps: number[];
  tools: { name: string; n: number }[];
}) {
  const totalCalls = tools.reduce((sum, t) => sum + t.n, 0);
  return (
    <aside className="task-rail">
      <div>
        <div className="head">Run</div>
        <div className="stat-grid">
          <div className="stat">
            <div className="v num">{steps.length}</div>
            <div className="k">iterations</div>
          </div>
          <div className="stat">
            <div className="v num">{totalCalls}</div>
            <div className="k">tool calls</div>
          </div>
        </div>
      </div>

      <div>
        <div className="head">Steps</div>
        <div className="steps">
          {steps.length === 0 ? (
            <span style={{ color: "var(--muted)", fontSize: 12, padding: "5px 8px", display: "block" }}>
              No iterations yet.
            </span>
          ) : (
            steps.map((iteration) => (
              <a key={iteration}>
                <span className="n">{String(iteration).padStart(2, "0")}</span>
                Iteration {iteration}
              </a>
            ))
          )}
        </div>
      </div>

      {tools.length > 0 && (
        <div>
          <div className="head">Tools used</div>
          <div className="tools">
            {tools.map(({ name, n }) => (
              <span key={name} className="tag">{name} × {n}</span>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}
