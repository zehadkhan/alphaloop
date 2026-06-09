import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST() {
  try {
    const res = await fetch(`${BACKEND}/run`, {
      method: "POST",
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.ok ? 200 : 500 });
  } catch (err) {
    return NextResponse.json(
      { status: "error", error: String(err) },
      { status: 502 }
    );
  }
}
