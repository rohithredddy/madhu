/** Loading and error states, the same everywhere (docs/04 section 5). */
export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="loading">{what}…</p>;
}

export function ErrorNotice({ message }: { message: string | null }) {
  if (!message) {
    return null;
  }
  return (
    <div className="notice error" role="alert">
      {message}
    </div>
  );
}
