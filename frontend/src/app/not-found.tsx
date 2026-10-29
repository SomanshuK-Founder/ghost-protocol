import Link from "next/link";
export default function NotFound() {
  return (
    <section className="empty">
      <h1>Record not found.</h1>
      <p>
        Return to the workspace to inspect the current owner-scoped records.
      </p>
      <Link href="/" className="button secondary">
        Back to overview
      </Link>
    </section>
  );
}
