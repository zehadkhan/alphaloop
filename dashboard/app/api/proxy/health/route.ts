import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  const [backendResult, priceResult] = await Promise.allSettled([
    fetch(`${BACKEND}/health`, { cache: "no-store" }),
    fetch("https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT", {
      cache: "no-store",
    }),
  ]);

  const health =
    backendResult.status === "fulfilled" && backendResult.value.ok
      ? await backendResult.value.json()
      : { status: "unreachable" };

  let bnb_price: number | null = null;
  if (priceResult.status === "fulfilled" && priceResult.value.ok) {
    const data = await priceResult.value.json();
    bnb_price = parseFloat(data.price);
  }

  return NextResponse.json({ ...health, bnb_price });
}
