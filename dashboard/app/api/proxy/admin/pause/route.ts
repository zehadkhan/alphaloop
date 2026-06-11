import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST() {
  try {
    const res = await fetch(`${BACKEND}/admin/pause`, {
      method: "POST",
      cache: "no-store",
    });
    return NextResponse.json(await res.json());
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
