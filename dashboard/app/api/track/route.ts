import { NextResponse } from "next/server";
import { Pool } from "pg";

const pool = process.env.NEON_DATABASE_URL
  ? new Pool({ connectionString: process.env.NEON_DATABASE_URL, ssl: { rejectUnauthorized: false } })
  : null;

export async function POST(req: Request) {
  if (!pool) return NextResponse.json({ ok: false, reason: "no db" });

  try {
    const { page } = await req.json().catch(() => ({ page: "/" }));

    // Get real IP
    const forwarded = req.headers.get("x-forwarded-for");
    const ip = forwarded ? forwarded.split(",")[0].trim() : "unknown";

    // Geo lookup (free, no key needed)
    let country = "Unknown";
    let city = "Unknown";
    if (ip !== "unknown" && ip !== "127.0.0.1" && !ip.startsWith("192.168")) {
      try {
        const geo = await fetch(`https://ipapi.co/${ip}/json/`, { signal: AbortSignal.timeout(3000) });
        if (geo.ok) {
          const g = await geo.json();
          country = g.country_name ?? "Unknown";
          city = g.city ?? "Unknown";
        }
      } catch {}
    }

    // Check if repeat visitor
    const existing = await pool.query(
      "SELECT id FROM visitor_logs WHERE ip = $1 LIMIT 1",
      [ip]
    );
    const is_repeat = existing.rowCount !== null && existing.rowCount > 0;

    await pool.query(
      `INSERT INTO visitor_logs (ip, country, city, page, is_repeat)
       VALUES ($1, $2, $3, $4, $5)`,
      [ip, country, city, page ?? "/", is_repeat]
    );

    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ ok: false, error: String(err) }, { status: 500 });
  }
}
