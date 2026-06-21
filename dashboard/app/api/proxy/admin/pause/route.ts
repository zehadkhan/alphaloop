import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(req: Request) {
  try {
    const password = req.headers.get("x-admin-password") ?? "";
    const res = await fetch(`${BACKEND}/admin/pause`, {
      method: "POST",
      headers: { "x-admin-password": password },
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
