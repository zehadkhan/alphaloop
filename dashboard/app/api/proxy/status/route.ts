import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/status`, { cache: "no-store" });
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
