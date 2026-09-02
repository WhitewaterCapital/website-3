type SearchParams = Promise<{ next?: string; error?: string }>;

export default async function LoginPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const { next = "/dashboard", error } = await searchParams;

  return (
    <main className="mx-auto flex min-h-[70vh] max-w-sm flex-col justify-center px-5">
      <h1 className="text-xl font-semibold">Members sign in</h1>
      <p className="mt-1 text-sm text-foreground/60">
        Enter the shared club passcode to reach the private dashboard.
      </p>

      <form action="/api/login" method="post" className="mt-6 space-y-3">
        <input type="hidden" name="next" value={next} />
        <input
          type="password"
          name="passcode"
          placeholder="Passcode"
          autoFocus
          className="w-full rounded-md border border-black/15 dark:border-white/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-foreground/40"
        />
        {error ? (
          <p className="text-sm text-rose-500">Wrong passcode — try again.</p>
        ) : null}
        <button className="w-full rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background">
          Enter
        </button>
      </form>

      <p className="mt-6 text-xs text-foreground/40">
        Placeholder shared-passcode gate (default <code>letmein</code>, set{" "}
        <code>MEMBER_PASSCODE</code> to change). Swap for per-member auth before
        going live.
      </p>
    </main>
  );
}
