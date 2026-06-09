import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const limit = searchParams.get("limit") ?? "50";

  try {
    const res = await fetch(`${BACKEND}/trades?limit=${limit}`, {
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({ count: 0, trades: [], error: String(err) });
  }
}
