export function SkeletonLine({
  width = "100%",
  className = "",
}: {
  width?: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={"skeleton-line " + className}
      style={{ width }}
    />
  );
}

export function SkeletonRows({
  count = 5,
  lead = true,
}: {
  count?: number;
  lead?: boolean;
}) {
  return (
    <div aria-hidden="true" className="skeleton-rows">
      {Array.from({ length: count }, (_, index) => (
        <div className="skeleton-row" key={index}>
          {lead ? <span className="skeleton-avatar" /> : null}
          <span className="skeleton-row-copy">
            <SkeletonLine width={index % 2 === 0 ? "38%" : "55%"} />
            <SkeletonLine width={index % 2 === 0 ? "62%" : "44%"} />
          </span>
          <SkeletonLine className="skeleton-amount" width="64px" />
        </div>
      ))}
    </div>
  );
}
