import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const ADMIN_PW = process.env.ADMIN_PASSWORD ?? "";

export async function POST(_req: Request, { params }: { params: { id: string } }) {
  try {
    const res = await fetch(`${BACKEND}/admin/close/${params.id}`, {
      method: "POST",
      headers: { "x-admin-password": ADMIN_PW },
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.ok ? 200 : res.status });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
