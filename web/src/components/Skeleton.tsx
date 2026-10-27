import s from "./Skeleton.module.css";

/** A placeholder in the shape of the content that is loading. */
export function Skeleton({ width = "100%", height = "1em", radius }: { width?: string; height?: string; radius?: string }) {
  return <span className={s.bone} style={{ width, height, borderRadius: radius }} aria-hidden />;
}

export function SkeletonLines({ lines = 3, label }: { lines?: number; label: string }) {
  return (
    <div className={s.lines} role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={`${92 - ((i * 17) % 40)}%`} />
      ))}
    </div>
  );
}
