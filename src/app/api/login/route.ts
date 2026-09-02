import { NextResponse } from "next/server";
import { AUTH_COOKIE, isValidPasscode } from "@/lib/auth";

export async function POST(req: Request) {
  const form = await req.formData();
  const passcode = String(form.get("passcode") ?? "");
  const next = String(form.get("next") ?? "/dashboard") || "/dashboard";

  if (!isValidPasscode(passcode)) {
    const url = new URL("/login", req.url);
    url.searchParams.set("error", "1");
    if (next) url.searchParams.set("next", next);
    return NextResponse.redirect(url, { status: 303 });
  }

  const res = NextResponse.redirect(new URL(next, req.url), { status: 303 });
  res.cookies.set(AUTH_COOKIE, "ok", {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });
  return res;
}
