const BACKEND_URL = process.env.FASTAPI_URL ?? "http://localhost:8000"

export async function GET(req: Request) {
  try {
    const upstream = await fetch(`${BACKEND_URL}/api/regulations/handbook-sync-status`, {
      method: "GET",
      signal: req.signal,
    })

    const headers = new Headers()
    const contentType = upstream.headers.get("Content-Type") ?? "application/json"
    headers.set("Content-Type", contentType)

    return new Response(upstream.body, {
      status: upstream.status,
      headers,
    })
  } catch {
    return Response.json({
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: "Backend unavailable",
    }, { status: 200 })
  }
}
