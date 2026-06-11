import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/twak/status`, { cache: "no-store" });
    if (!res.ok) return NextResponse.json({ error: "backend_error" }, { status: res.status });
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ error: "unreachable" }, { status: 503 });
  }
}
