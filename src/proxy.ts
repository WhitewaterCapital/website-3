import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { AUTH_COOKIE } from "@/lib/auth";

// Guard the members-only sections. The public track record ("/") stays open.
const PROTECTED = [
  "/dashboard",
  "/sentiment",
  "/stress-test",
  "/nova",
  "/intra-exitus",
  "/models",
  "/members",
  "/proposals",
];

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const needsAuth = PROTECTED.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );
  if (!needsAuth) return NextResponse.next();

  const authed = req.cookies.get(AUTH_COOKIE)?.value === "ok";
  if (authed) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/sentiment/:path*",
    "/stress-test/:path*",
    "/nova/:path*",
    "/intra-exitus/:path*",
    "/models/:path*",
    "/members/:path*",
    "/proposals/:path*",
  ],
};
